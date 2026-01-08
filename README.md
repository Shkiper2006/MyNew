# MyNew

## Server

The server implementation lives in `server/` and uses **FastAPI + WebSocket** with JSON persistence in `server/DB.dat`.

### Requirements

```bash
python -m venv .venv
. .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r server/requirements.txt
```

### Run

```bash
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

> Note: On Windows Server 2025, bind to `0.0.0.0` so the service listens on the external IP (e.g. `89.110.93.27`).

### Endpoints

- `POST /register` – регистрация
- `POST /login` – вход
- `POST /logout` – выход
- `GET /users` – список пользователей (online/offline)
- `POST /rooms` – создание комнаты
- `POST /invites` – отправка приглашения
- `POST /invites/{invite_id}/accept` – принятие приглашения
- `POST /invites/{invite_id}/decline` – отказ
- `POST /rooms/{room_id}/messages` – отправка сообщений/вложений
- `GET /rooms/{room_id}/messages` – история сообщений
- `GET /health` – проверка статуса
- `WS /ws?user=USERNAME` – события online/offline, приглашения, сообщения
