import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parent / "DB.dat"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def hash_password(password: str) -> str:
    return sha256(password.encode("utf-8")).hexdigest()


class DataStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        return {
            "users": {},
            "sessions": {},
            "rooms": {},
            "invites": {},
            "messages": [],
        }

    def _save(self) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2)

    def register_user(self, username: str, password: str) -> None:
        with self.lock:
            if username in self.data["users"]:
                raise ValueError("user_exists")
            self.data["users"][username] = {
                "password_hash": hash_password(password),
                "created_at": utc_now(),
                "online": False,
                "last_seen": None,
            }
            self._save()

    def verify_user(self, username: str, password: str) -> bool:
        user = self.data["users"].get(username)
        if not user:
            return False
        return user["password_hash"] == hash_password(password)

    def create_session(self, username: str) -> str:
        token = secrets.token_hex(16)
        with self.lock:
            self.data["sessions"][token] = {
                "username": username,
                "created_at": utc_now(),
            }
            self.set_online(username, True, save=False)
            self._save()
        return token

    def drop_session(self, token: str) -> None:
        with self.lock:
            session = self.data["sessions"].pop(token, None)
            if session:
                self.set_online(session["username"], False, save=False)
            self._save()

    def username_from_token(self, token: str) -> Optional[str]:
        session = self.data["sessions"].get(token)
        if not session:
            return None
        return session["username"]

    def list_users(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [
                {
                    "username": username,
                    "online": info.get("online", False),
                    "last_seen": info.get("last_seen"),
                }
                for username, info in self.data["users"].items()
            ]

    def set_online(self, username: str, online: bool, save: bool = True) -> None:
        user = self.data["users"].get(username)
        if not user:
            return
        user["online"] = online
        user["last_seen"] = utc_now()
        if save:
            self._save()

    def create_room(self, name: str, owner: str, members: Optional[List[str]] = None) -> str:
        room_id = secrets.token_hex(8)
        member_list = sorted(set([owner] + (members or [])))
        with self.lock:
            self.data["rooms"][room_id] = {
                "room_id": room_id,
                "name": name,
                "owner": owner,
                "members": member_list,
                "created_at": utc_now(),
            }
            self._save()
        return room_id

    def list_rooms_for_user(self, username: str) -> List[Dict[str, Any]]:
        with self.lock:
            return [
                room
                for room in self.data["rooms"].values()
                if username in room.get("members", [])
            ]

    def add_member_to_room(self, room_id: str, username: str) -> None:
        with self.lock:
            room = self.data["rooms"].get(room_id)
            if not room:
                raise ValueError("room_not_found")
            if username not in room["members"]:
                room["members"].append(username)
                room["members"].sort()
            self._save()

    def create_invite(self, from_user: str, to_user: str, room_id: str) -> str:
        invite_id = secrets.token_hex(8)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        with self.lock:
            if room_id not in self.data["rooms"]:
                raise ValueError("room_not_found")
            self.data["invites"][invite_id] = {
                "invite_id": invite_id,
                "from_user": from_user,
                "to_user": to_user,
                "room_id": room_id,
                "status": "pending",
                "created_at": utc_now(),
                "expires_at": expires_at,
            }
            self._save()
        return invite_id

    def expire_invites(self) -> None:
        now = datetime.now(timezone.utc)
        expired = []
        for invite_id, invite in self.data["invites"].items():
            if invite["status"] == "pending" and parse_time(invite["expires_at"]) < now:
                expired.append(invite_id)
        if expired:
            for invite_id in expired:
                self.data["invites"][invite_id]["status"] = "expired"
            self._save()

    def list_invites_for_user(self, username: str) -> List[Dict[str, Any]]:
        with self.lock:
            self.expire_invites()
            return [
                invite
                for invite in self.data["invites"].values()
                if invite["to_user"] == username
            ]

    def get_invite(self, invite_id: str) -> Dict[str, Any]:
        with self.lock:
            self.expire_invites()
            invite = self.data["invites"].get(invite_id)
            if not invite:
                raise ValueError("invite_not_found")
            return invite

    def update_invite_status(self, invite_id: str, status: str) -> Dict[str, Any]:
        with self.lock:
            self.expire_invites()
            invite = self.data["invites"].get(invite_id)
            if not invite:
                raise ValueError("invite_not_found")
            invite["status"] = status
            self._save()
            return invite

    def add_message(
        self,
        room_id: str,
        sender: str,
        content: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        message = {
            "message_id": secrets.token_hex(8),
            "room_id": room_id,
            "sender": sender,
            "content": content,
            "attachments": attachments or [],
            "images": images or [],
            "created_at": utc_now(),
        }
        with self.lock:
            if room_id not in self.data["rooms"]:
                raise ValueError("room_not_found")
            self.data["messages"].append(message)
            self._save()
        return message

    def list_messages(self, room_id: str) -> List[Dict[str, Any]]:
        with self.lock:
            return [
                message for message in self.data["messages"] if message["room_id"] == room_id
            ]
