import asyncio
import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

DB_PATH = os.path.join(os.path.dirname(__file__), "DB.dat")
INVITE_TIMEOUT_SECONDS = 5 * 60

app = FastAPI(title="Chat Server")


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


def get_db() -> Dict[str, Any]:
    return load_db()


def update_user_status(data: Dict[str, Any], username: str, online: bool) -> None:
    user = data["users"].get(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["online"] = online
    user["last_seen"] = utc_now_iso()


def cleanup_expired_invites(data: Dict[str, Any]) -> None:
    now_ts = time.time()
    expired = []
    for invite_id, invite in data["invitations"].items():
        if invite["status"] != "pending":
            continue
        if now_ts - invite["created_at"] > INVITE_TIMEOUT_SECONDS:
            expired.append(invite_id)
    for invite_id in expired:
        data["invitations"][invite_id]["status"] = "expired"


@app.post("/register")
async def register(payload: RegisterRequest) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        if payload.username in data["users"]:
            raise HTTPException(status_code=409, detail="User already exists")
        data["users"][payload.username] = {
            "password": payload.password,
            "online": False,
            "last_seen": utc_now_iso(),
        }
        save_db(data)
    return {"status": "ok"}


@app.post("/login")
async def login(payload: LoginRequest) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        user = data["users"].get(payload.username)
        if not user or user["password"] != payload.password:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        update_user_status(data, payload.username, True)
        save_db(data)
    await manager.broadcast({"type": "status", "user": payload.username, "online": True})
    return {"status": "ok"}


@app.post("/logout")
async def logout(payload: LoginRequest) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        user = data["users"].get(payload.username)
        if not user or user["password"] != payload.password:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        update_user_status(data, payload.username, False)
        save_db(data)
    await manager.broadcast({"type": "status", "user": payload.username, "online": False})
    return {"status": "ok"}


@app.get("/users")
async def list_users() -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        users = [
            {
                "username": username,
                "online": info["online"],
                "last_seen": info["last_seen"],
            }
            for username, info in data["users"].items()
        ]
    return {"users": users}


@app.post("/rooms")
async def create_room(payload: RoomCreateRequest) -> Dict[str, Any]:
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
            "created_at": utc_now_iso(),
        }
        save_db(data)
    await manager.broadcast({"type": "room_created", "room_id": room_id, "name": payload.name})
    return {"room_id": room_id}


@app.post("/invites")
async def create_invite(payload: InviteCreateRequest) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        cleanup_expired_invites(data)
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
    await manager.send_personal(
        payload.recipient,
        {"type": "invite", "invite_id": invite_id, "room_id": payload.room_id, "from": payload.sender},
    )
    return {"invite_id": invite_id}


@app.post("/invites/{invite_id}/accept")
async def accept_invite(invite_id: str) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        cleanup_expired_invites(data)
        invite = data["invitations"].get(invite_id)
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Invite is {invite['status']}")
        invite["status"] = "accepted"
        room = data["rooms"].get(invite["room_id"])
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        if invite["recipient"] not in room["members"]:
            room["members"].append(invite["recipient"])
        save_db(data)
    await manager.send_personal(
        invite["sender"],
        {"type": "invite_response", "invite_id": invite_id, "status": "accepted"},
    )
    return {"status": "accepted"}


@app.post("/invites/{invite_id}/decline")
async def decline_invite(invite_id: str) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        cleanup_expired_invites(data)
        invite = data["invitations"].get(invite_id)
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Invite is {invite['status']}")
        invite["status"] = "declined"
        save_db(data)
    await manager.send_personal(
        invite["sender"],
        {"type": "invite_response", "invite_id": invite_id, "status": "declined"},
    )
    return {"status": "declined"}


@app.post("/rooms/{room_id}/messages")
async def send_message(room_id: str, payload: MessageCreateRequest) -> Dict[str, Any]:
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
async def list_messages(room_id: str) -> Dict[str, Any]:
    async with state_lock:
        data = get_db()
        if room_id not in data["rooms"]:
            raise HTTPException(status_code=404, detail="Room not found")
        messages = [msg for msg in data["messages"].values() if msg["room_id"] == room_id]
    return {"messages": messages}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    username = websocket.query_params.get("user")
    if not username:
        await websocket.close(code=1008)
        return
    async with state_lock:
        data = get_db()
        if username not in data["users"]:
            await websocket.close(code=1008)
            return
        update_user_status(data, username, True)
        save_db(data)
    await manager.connect(username, websocket)
    await manager.broadcast({"type": "status", "user": username, "online": True})
    try:
        while True:
            await websocket.receive_text()
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
