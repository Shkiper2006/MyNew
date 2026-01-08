from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .db import DataStore

app = FastAPI(title="Chat Server")
store = DataStore()


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenRequest(BaseModel):
    token: str


class RoomCreateRequest(BaseModel):
    token: str
    name: str
    members: Optional[List[str]] = None


class InviteRequest(BaseModel):
    token: str
    to_user: str
    room_id: str


class InviteActionRequest(BaseModel):
    token: str


class MessageRequest(BaseModel):
    token: str
    room_id: str
    content: str
    attachments: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[Dict[str, Any]]] = None


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.connection_users: Dict[WebSocket, str] = {}
        self.connection_rooms: Dict[WebSocket, str] = {}

    async def connect(self, room_id: str, username: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.setdefault(room_id, []).append(websocket)
        self.connection_users[websocket] = username
        self.connection_rooms[websocket] = room_id

    def disconnect(self, websocket: WebSocket) -> None:
        room_id = self.connection_rooms.pop(websocket, None)
        if room_id and room_id in self.active_connections:
            self.active_connections[room_id] = [
                ws for ws in self.active_connections[room_id] if ws != websocket
            ]
        self.connection_users.pop(websocket, None)

    async def broadcast(self, room_id: str, message: Dict[str, Any]) -> None:
        for connection in self.active_connections.get(room_id, []):
            await connection.send_json(message)

    def active_count_for_user(self, username: str) -> int:
        return sum(1 for user in self.connection_users.values() if user == username)


manager = ConnectionManager()


def require_user(token: str) -> str:
    username = store.username_from_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return username


@app.post("/register")
def register(payload: RegisterRequest) -> Dict[str, Any]:
    try:
        store.register_user(payload.username, payload.password)
    except ValueError:
        raise HTTPException(status_code=400, detail="User already exists")
    return {"status": "ok"}


@app.post("/login")
def login(payload: LoginRequest) -> Dict[str, Any]:
    if not store.verify_user(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = store.create_session(payload.username)
    return {"token": token}


@app.post("/logout")
def logout(payload: TokenRequest) -> Dict[str, Any]:
    store.drop_session(payload.token)
    return {"status": "ok"}


@app.get("/users")
def list_users() -> Dict[str, Any]:
    return {"users": store.list_users()}


@app.post("/rooms")
def create_room(payload: RoomCreateRequest) -> Dict[str, Any]:
    username = require_user(payload.token)
    room_id = store.create_room(payload.name, username, payload.members)
    return {"room_id": room_id}


@app.get("/rooms")
def list_rooms(token: str) -> Dict[str, Any]:
    username = require_user(token)
    return {"rooms": store.list_rooms_for_user(username)}


@app.post("/invites")
def create_invite(payload: InviteRequest) -> Dict[str, Any]:
    username = require_user(payload.token)
    invite_id = store.create_invite(username, payload.to_user, payload.room_id)
    return {"invite_id": invite_id}


@app.get("/invites")
def list_invites(token: str) -> Dict[str, Any]:
    username = require_user(token)
    return {"invites": store.list_invites_for_user(username)}


@app.post("/invites/{invite_id}/accept")
def accept_invite(invite_id: str, payload: InviteActionRequest) -> Dict[str, Any]:
    username = require_user(payload.token)
    invite = store.get_invite(invite_id)
    if invite["to_user"] != username:
        raise HTTPException(status_code=403, detail="Not allowed")
    invite = store.update_invite_status(invite_id, "accepted")
    store.add_member_to_room(invite["room_id"], username)
    return {"status": "accepted"}


@app.post("/invites/{invite_id}/decline")
def decline_invite(invite_id: str, payload: InviteActionRequest) -> Dict[str, Any]:
    username = require_user(payload.token)
    invite = store.get_invite(invite_id)
    if invite["to_user"] != username:
        raise HTTPException(status_code=403, detail="Not allowed")
    invite = store.update_invite_status(invite_id, "declined")
    return {"status": "declined"}


@app.post("/messages")
def send_message(payload: MessageRequest) -> Dict[str, Any]:
    username = require_user(payload.token)
    message = store.add_message(
        payload.room_id,
        username,
        payload.content,
        payload.attachments,
        payload.images,
    )
    return {"message": message}


@app.get("/rooms/{room_id}/messages")
def list_messages(room_id: str, token: str) -> Dict[str, Any]:
    username = require_user(token)
    rooms = store.list_rooms_for_user(username)
    if room_id not in {room["room_id"] for room in rooms}:
        raise HTTPException(status_code=403, detail="Not a member")
    return {"messages": store.list_messages(room_id)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str, room_id: str) -> None:
    username = store.username_from_token(token)
    if not username:
        await websocket.close(code=1008)
        return
    await manager.connect(room_id, username, websocket)
    store.set_online(username, True)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "send_message":
                message = store.add_message(
                    room_id,
                    username,
                    data.get("content", ""),
                    data.get("attachments"),
                    data.get("images"),
                )
                await manager.broadcast(room_id, {"event": "message", "data": message})
            else:
                await websocket.send_json({"event": "error", "detail": "Unknown action"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        if manager.active_count_for_user(username) == 0:
            store.set_online(username, False)
