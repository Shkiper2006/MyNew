import asyncio
import base64
import contextlib
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel, Field

DB_PATH = os.path.join(os.path.dirname(__file__), "DB.dat")
INVITE_TIMEOUT_SECONDS = 5 * 60
INVITE_CLEANUP_INTERVAL = 10

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(expire_invites_task())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(title="Chat Server", lifespan=lifespan)


class TokenAuth(BaseModel):
    token: str


class Attachment(BaseModel):
    name: str
    mime_type: str
    data_base64: str

    def validate_base64(self) -> None:
        try:
            base64.b64decode(self.data_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid base64: {exc}")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    username: str
    password: str


class RoomCreateRequest(BaseModel):
    name: str
    owner: str
    room_type: str = Field("text", pattern="^(text|voice)$")
    members: List[str] = Field(default_factory=list)


class InviteCreateRequest(BaseModel):
    sender: str
    recipient: str
    room_id: str


class MessageCreateRequest(BaseModel):
    sender: str
    content: str
    attachments: List[Attachment] = Field(default_factory=list)


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: Dict[str, WebSocket] = {}
        self.lock = asyncio.Lock()

    async def connect(self, username: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self.lock:
            self.connections[username] = websocket

    async def disconnect(self, username: str) -> None:
        async with self.lock:
            self.connections.pop(username, None)

    async def send_personal(self, username: str, payload: Dict[str, Any]) -> None:
        async with self.lock:
            websocket = self.connections.get(username)
        if websocket:
            await websocket.send_json(payload)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        async with self.lock:
            websockets = list(self.connections.values())
        for websocket in websockets:
            await websocket.send_json(payload)


manager = ConnectionManager()
state_lock = asyncio.Lock()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


app.mount(
    "/static",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")),
    name="static",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_db() -> Dict[str, Any]:
    if not os.path.exists(DB_PATH):
        return {
            "users": {},
            "rooms": {},
            "invitations": {},
            "messages": {},
        }
    with open(DB_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_db(data: Dict[str, Any]) -> None:
    with open(DB_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def ensure_password_hash(user: Dict[str, Any], raw_password: str) -> bool:
    if "password_hash" in user:
        return pwd_context.verify(raw_password, user["password_hash"])
    if user.get("password") == raw_password:
        user["password_hash"] = pwd_context.hash(raw_password)
        user.pop("password", None)
        return True
    return False


def update_user_status(data: Dict[str, Any], username: str, online: bool) -> None:
    user = data["users"].get(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["online"] = online
    user["last_seen"] = utc_now_iso()


def cleanup_expired_invites(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    now_ts = time.time()
    expired_events = []
    for invite_id, invite in data["invitations"].items():
        if invite["status"] != "pending":
            continue
        if now_ts - invite["created_at"] > INVITE_TIMEOUT_SECONDS:
            invite["status"] = "expired"
            expired_events.append(
                {
                    "invite_id": invite_id,
                    "sender": invite["sender"],
                    "recipient": invite["recipient"],
                    "room_id": invite["room_id"],
                }
            )
    return expired_events


def authenticate_token(token: Optional[str], data: Dict[str, Any]) -> str:
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    for username, info in data["users"].items():
        if info.get("token") == token:
            return username
    raise HTTPException(status_code=401, detail="Invalid token")


def get_authenticated_user(x_auth_token: Optional[str] = Header(default=None)) -> str:
    data = load_db()
    return authenticate_token(x_auth_token, data)


async def expire_invites_task() -> None:
    while True:
        await asyncio.sleep(INVITE_CLEANUP_INTERVAL)
        async with state_lock:
            data = get_db()
            expired_events = cleanup_expired_invites(data)
            if expired_events:
                save_db(data)
        for event in expired_events:
            payload = {"type": "invite_response", "invite_id": event["invite_id"], "status": "expired"}
            await manager.send_personal(event["sender"], payload)
            await manager.send_personal(event["recipient"], payload)


def get_db() -> Dict[str, Any]:
    return load_db()


@app.post("/register")
async def register(payload: RegisterRequest) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        if payload.username in data["users"]:
            raise HTTPException(status_code=409, detail="User already exists")
        data["users"][payload.username] = {
            "password_hash": pwd_context.hash(payload.password),
            "online": False,
            "last_seen": utc_now_iso(),
            "token": None,
        }
        save_db(data)
    return {"status": "ok"}


@app.post("/login")
async def login(payload: LoginRequest) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        user = data["users"].get(payload.username)
        if not user or not ensure_password_hash(user, payload.password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = str(uuid.uuid4())
        user["token"] = token
        update_user_status(data, payload.username, True)
        save_db(data)
    await manager.broadcast({"type": "status", "user": payload.username, "online": True})
    return {"status": "ok", "token": token}


@app.post("/logout")
async def logout(auth: TokenAuth) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        username = authenticate_token(auth.token, data)
        user = data["users"].get(username)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        user["token"] = None
        update_user_status(data, username, False)
        save_db(data)
    await manager.broadcast({"type": "status", "user": username, "online": False})
    return {"status": "ok"}


@app.get("/users")
async def list_users() -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        users = [
            {
                "username": username,
                "online": info.get("online", False),
                "last_seen": info.get("last_seen"),
            }
            for username, info in data["users"].items()
        ]
    return {"users": users}


@app.get("/rooms")
async def list_rooms(user: str = Query(..., min_length=3), token: str = Depends(get_authenticated_user)) -> Dict[str, Any]:
    if user != token:
        raise HTTPException(status_code=403, detail="User mismatch")
    async with state_lock:
        data = get_db()
        rooms = [
            {"id": room_id, **info}
            for room_id, info in data["rooms"].items()
            if user in info.get("members", [])
        ]
    return {"rooms": rooms}


@app.get("/rooms/{room_id}")
async def get_room(room_id: str, token: str = Depends(get_authenticated_user)) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        room = data["rooms"].get(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        if token not in room.get("members", []):
            raise HTTPException(status_code=403, detail="Not a room member")
    return {"room": {"id": room_id, **room}}


@app.post("/rooms")
async def create_room(payload: RoomCreateRequest, token: str = Depends(get_authenticated_user)) -> Dict[str, Any]:
    if payload.owner != token:
        raise HTTPException(status_code=403, detail="Owner mismatch")
    async with state_lock:
        data = get_db()
        if payload.owner not in data["users"]:
            raise HTTPException(status_code=404, detail="Owner not found")
        for member in payload.members:
            if member not in data["users"]:
                raise HTTPException(status_code=404, detail=f"Member {member} not found")
        room_id = str(uuid.uuid4())
        members = sorted(set([payload.owner, *payload.members]))
        data["rooms"][room_id] = {
            "name": payload.name,
            "members": members,
            "room_type": payload.room_type,
            "created_at": utc_now_iso(),
        }
        save_db(data)
    await manager.broadcast({"type": "room_created", "room_id": room_id, "name": payload.name})
    return {"room_id": room_id}


@app.post("/invites")
async def create_invite(payload: InviteCreateRequest, token: str = Depends(get_authenticated_user)) -> Dict[str, Any]:
    if payload.sender != token:
        raise HTTPException(status_code=403, detail="Sender mismatch")
    async with state_lock:
        data = get_db()
        expired_events = cleanup_expired_invites(data)
        if payload.sender not in data["users"]:
            raise HTTPException(status_code=404, detail="Sender not found")
        if payload.recipient not in data["users"]:
            raise HTTPException(status_code=404, detail="Recipient not found")
        if payload.room_id not in data["rooms"]:
            raise HTTPException(status_code=404, detail="Room not found")
        invite_id = str(uuid.uuid4())
        data["invitations"][invite_id] = {
            "sender": payload.sender,
            "recipient": payload.recipient,
            "room_id": payload.room_id,
            "status": "pending",
            "created_at": time.time(),
        }
        save_db(data)
    for event in expired_events:
        payload_event = {"type": "invite_response", "invite_id": event["invite_id"], "status": "expired"}
        await manager.send_personal(event["sender"], payload_event)
        await manager.send_personal(event["recipient"], payload_event)
    await manager.send_personal(
        payload.recipient,
        {"type": "invite", "invite_id": invite_id, "room_id": payload.room_id, "from": payload.sender},
    )
    return {"invite_id": invite_id}


@app.post("/invites/{invite_id}/accept")
async def accept_invite(invite_id: str, token: str = Depends(get_authenticated_user)) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        expired_events = cleanup_expired_invites(data)
        invite = data["invitations"].get(invite_id)
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Invite is {invite['status']}")
        if invite["recipient"] != token:
            raise HTTPException(status_code=403, detail="Not invite recipient")
        invite["status"] = "accepted"
        room = data["rooms"].get(invite["room_id"])
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        if invite["recipient"] not in room["members"]:
            room["members"].append(invite["recipient"])
        save_db(data)
    for event in expired_events:
        payload_event = {"type": "invite_response", "invite_id": event["invite_id"], "status": "expired"}
        await manager.send_personal(event["sender"], payload_event)
        await manager.send_personal(event["recipient"], payload_event)
    await manager.send_personal(
        invite["sender"],
        {"type": "invite_response", "invite_id": invite_id, "status": "accepted"},
    )
    return {"status": "accepted"}


@app.post("/invites/{invite_id}/decline")
async def decline_invite(invite_id: str, token: str = Depends(get_authenticated_user)) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        expired_events = cleanup_expired_invites(data)
        invite = data["invitations"].get(invite_id)
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Invite is {invite['status']}")
        if invite["recipient"] != token:
            raise HTTPException(status_code=403, detail="Not invite recipient")
        invite["status"] = "declined"
        save_db(data)
    for event in expired_events:
        payload_event = {"type": "invite_response", "invite_id": event["invite_id"], "status": "expired"}
        await manager.send_personal(event["sender"], payload_event)
        await manager.send_personal(event["recipient"], payload_event)
    await manager.send_personal(
        invite["sender"],
        {"type": "invite_response", "invite_id": invite_id, "status": "declined"},
    )
    return {"status": "declined"}


@app.post("/rooms/{room_id}/messages")
async def send_message(
    room_id: str, payload: MessageCreateRequest, token: str = Depends(get_authenticated_user)
) -> Dict[str, Any]:
    if payload.sender != token:
        raise HTTPException(status_code=403, detail="Sender mismatch")
    async with state_lock:
        data = get_db()
        room = data["rooms"].get(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        if payload.sender not in room["members"]:
            raise HTTPException(status_code=403, detail="Sender not in room")
        for attachment in payload.attachments:
            attachment.validate_base64()
        message_id = str(uuid.uuid4())
        entry = {
            "id": message_id,
            "room_id": room_id,
            "sender": payload.sender,
            "content": payload.content,
            "attachments": [attachment.dict() for attachment in payload.attachments],
            "created_at": utc_now_iso(),
        }
        data["messages"][message_id] = entry
        save_db(data)
    await manager.broadcast({"type": "message", **entry})
    return {"message_id": message_id}


@app.get("/rooms/{room_id}/messages")
async def list_messages(room_id: str, token: str = Depends(get_authenticated_user)) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        room = data["rooms"].get(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        if token not in room.get("members", []):
            raise HTTPException(status_code=403, detail="Not a room member")
        messages = [msg for msg in data["messages"].values() if msg["room_id"] == room_id]
    return {"messages": messages}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    username = websocket.query_params.get("user")
    token = websocket.query_params.get("token")
    if not username or not token:
        await websocket.close(code=1008)
        return
    async with state_lock:
        data = get_db()
        try:
            auth_user = authenticate_token(token, data)
        except HTTPException:
            await websocket.close(code=1008)
            return
        if auth_user != username:
            await websocket.close(code=1008)
            return
        if username not in data["users"]:
            await websocket.close(code=1008)
            return
        update_user_status(data, username, True)
        save_db(data)
    await manager.connect(username, websocket)
    await manager.broadcast({"type": "status", "user": username, "online": True})
    try:
        while True:
            payload = await websocket.receive_json()
            if payload.get("type") == "signal":
                target = payload.get("to")
                if target:
                    await manager.send_personal(target, {"type": "signal", **payload})
            elif payload.get("type") == "ping":
                await manager.send_personal(username, {"type": "pong"})
    except WebSocketDisconnect:
        await manager.disconnect(username)
        async with state_lock:
            data = get_db()
            if username in data["users"]:
                update_user_status(data, username, False)
                save_db(data)
        await manager.broadcast({"type": "status", "user": username, "online": False})


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}
