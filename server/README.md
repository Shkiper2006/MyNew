# Chat server

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

- Все данные сохраняются в файле `server/DB.dat` в формате JSON.
- Для запуска на Windows Server 2025 и прослушивания внешнего IP 89.110.93.27 используйте `--host 0.0.0.0`, а в фаерволе разрешите входящие на нужный порт.

## Основные эндпоинты

- `POST /register` — регистрация
- `POST /login` — вход, возвращает токен
- `POST /logout` — выход
- `GET /users` — список пользователей с `online/offline`
- `POST /rooms` — создание комнаты
- `GET /rooms` — список комнат пользователя
- `POST /invites` — отправка приглашения
- `GET /invites` — список приглашений
- `POST /invites/{invite_id}/accept` — принять приглашение
- `POST /invites/{invite_id}/decline` — отказаться
- `POST /messages` — отправка сообщений/вложений/изображений
- `GET /rooms/{room_id}/messages` — история сообщений
- `WS /ws?token=...&room_id=...` — WebSocket для сообщений
