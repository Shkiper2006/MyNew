# MyNew

## Сервер

Реализация сервера находится в `server/` и использует **FastAPI + WebSocket** с JSON-хранилищем в `server/DB.dat`.

### Требования

```bash
python -m venv .venv
. .venv/bin/activate  # В Windows: .venv\Scripts\activate
pip install -r server/requirements.txt
```

### Запуск

```bash
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

> Примечание: на Windows Server 2025 используйте `0.0.0.0`, чтобы сервис слушал внешний IP (например, `89.110.93.27`).

### Браузерный клиент (инструкция для начинающих)

1. Запустите сервер как показано выше.
2. Откройте браузер на сервере (или на своём ПК) и перейдите по адресу: `http://<IP_СЕРВЕРА>:8000/`.
3. Зарегистрируйтесь и выполните вход.
4. Создайте комнату (текстовую или голосовую) или откройте уже существующую.
5. Пригласите онлайн-пользователей из списка комнаты.

> Голосовой чат и демонстрация экрана используют WebRTC. В современных браузерах эти функции требуют HTTPS или `localhost`.  
> Для публичного доступа настройте HTTPS (например, через обратный прокси Nginx с TLS-сертификатом).

### Эндпоинты

- `POST /register` – регистрация
- `POST /login` – вход
- `POST /logout` – выход
- `GET /users` – список пользователей (online/offline)
- `GET /rooms?user=USERNAME` – список комнат пользователя
- `GET /rooms/{room_id}` – данные комнаты
- `POST /rooms` – создание комнаты
- `POST /invites` – отправка приглашения
- `POST /invites/{invite_id}/accept` – принятие приглашения
- `POST /invites/{invite_id}/decline` – отказ
- `POST /rooms/{room_id}/messages` – отправка сообщений/вложений
- `GET /rooms/{room_id}/messages` – история сообщений
- `GET /health` – проверка статуса
- `WS /ws?user=USERNAME` – события online/offline, приглашения, сообщения

> Большинство эндпоинтов требуют заголовок `X-Auth-Token`, который возвращается при `/login`.
