const authView = document.getElementById("authView");
const chatView = document.getElementById("chatView");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const userList = document.getElementById("userList");
const roomList = document.getElementById("roomList");
const inviteList = document.getElementById("inviteList");
const messageList = document.getElementById("messageList");
const emptyState = document.getElementById("emptyState");
const roomTitle = document.getElementById("roomTitle");
const roomMeta = document.getElementById("roomMeta");
const messageInput = document.getElementById("messageInput");
const sendMessageButton = document.getElementById("sendMessage");
const fileInput = document.getElementById("fileInput");
const composer = document.getElementById("composer");
const roomForm = document.getElementById("roomForm");
const roomNameInput = document.getElementById("roomName");
const roomInviteInput = document.getElementById("roomInvite");
const backToRooms = document.getElementById("backToRooms");
const serverUrlInput = document.getElementById("serverUrl");
const toast = document.getElementById("toast");
const emojiBar = document.getElementById("emojiBar");
const micSelect = document.getElementById("micSelect");
const micIndicator = document.getElementById("micIndicator");
const micLabel = document.getElementById("micLabel");
const micMeter = document.getElementById("micMeter");
const toggleMicButton = document.getElementById("toggleMic");
const shareScreenButton = document.getElementById("shareScreen");
const screenStatus = document.getElementById("screenStatus");

const emojiList = ["😀", "😅", "😍", "🤝", "🔥", "🎉", "👍", "🙏", "💬", "🚀"];

let currentUser = null;
let currentRoomId = null;
let socket = null;
let rooms = new Map();
let invites = new Map();
let messagesByRoom = new Map();
let micStream = null;
let micEnabled = false;
let audioContext = null;
let analyser = null;
let micAnimation = null;
let screenStream = null;

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(toast.dataset.timeoutId);
  const timeoutId = setTimeout(() => toast.classList.add("hidden"), 3000);
  toast.dataset.timeoutId = timeoutId;
}

function apiBase() {
  return serverUrlInput.value.replace(/\/$/, "");
}

async function fetchJson(path, options = {}) {
  const response = await fetch(`${apiBase()}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Ошибка запроса" }));
    throw new Error(payload.detail || "Ошибка запроса");
  }
  return response.json();
}

function setView(isAuthenticated) {
  if (isAuthenticated) {
    authView.classList.add("hidden");
    chatView.classList.remove("hidden");
  } else {
    authView.classList.remove("hidden");
    chatView.classList.add("hidden");
  }
}

function renderUsers(users) {
  userList.innerHTML = "";
  users.forEach((user) => {
    const li = document.createElement("li");
    li.className = user.online ? "" : "offline";
    li.innerHTML = `
      <div>
        <strong>${user.username}</strong>
        <div class="status">
          <span class="dot ${user.online ? "online" : ""}"></span>
          <span>${user.online ? "online" : "offline"}</span>
        </div>
      </div>
      <small>${new Date(user.last_seen).toLocaleString()}</small>
    `;
    userList.appendChild(li);
  });
}

function renderRooms() {
  roomList.innerHTML = "";
  rooms.forEach((room) => {
    const li = document.createElement("li");
    const info = document.createElement("div");
    info.innerHTML = `<strong>${room.name}</strong><div class="subtitle">${room.meta}</div>`;
    const actions = document.createElement("div");
    const openButton = document.createElement("button");
    openButton.textContent = "Открыть";
    openButton.addEventListener("click", () => openRoom(room.id));
    const inviteButton = document.createElement("button");
    inviteButton.textContent = "Пригласить";
    inviteButton.classList.add("secondary");
    inviteButton.addEventListener("click", () => sendInvite(room.id));
    actions.append(openButton, inviteButton);
    li.append(info, actions);
    roomList.appendChild(li);
  });
}

function renderInvites() {
  inviteList.innerHTML = "";
  invites.forEach((invite) => {
    const li = document.createElement("li");
    const info = document.createElement("div");
    const minutesLeft = Math.max(0, Math.ceil((invite.expiresAt - Date.now()) / 60000));
    info.innerHTML = `
      <strong>${invite.roomName}</strong>
      <div class="subtitle">От ${invite.from}</div>
      <div class="subtitle">Осталось ${minutesLeft} мин.</div>
    `;
    const actions = document.createElement("div");
    actions.className = "invite-actions";
    const acceptButton = document.createElement("button");
    acceptButton.textContent = "Принять";
    acceptButton.addEventListener("click", () => respondInvite(invite.id, true));
    const declineButton = document.createElement("button");
    declineButton.textContent = "Отказать";
    declineButton.classList.add("secondary");
    declineButton.addEventListener("click", () => respondInvite(invite.id, false));
    actions.append(acceptButton, declineButton);
    li.append(info, actions);
    inviteList.appendChild(li);
  });
}

function renderMessages(roomId) {
  messageList.innerHTML = "";
  const messages = messagesByRoom.get(roomId) || [];
  messages.forEach((message) => {
    const item = document.createElement("div");
    item.className = "message";
    const dateLabel = new Date(message.created_at).toLocaleString();
    item.innerHTML = `<div class="meta">${message.sender} • ${dateLabel}</div><div>${message.content}</div>`;
    if (message.attachments && message.attachments.length > 0) {
      const attachments = document.createElement("div");
      attachments.className = "attachments";
      message.attachments.forEach((attachment) => {
        if (attachment.mime_type.startsWith("image/")) {
          const img = document.createElement("img");
          img.src = `data:${attachment.mime_type};base64,${attachment.data_base64}`;
          img.alt = attachment.name;
          attachments.appendChild(img);
        } else {
          const link = document.createElement("a");
          link.href = `data:${attachment.mime_type};base64,${attachment.data_base64}`;
          link.textContent = attachment.name;
          link.download = attachment.name;
          attachments.appendChild(link);
        }
      });
      item.appendChild(attachments);
    }
    messageList.appendChild(item);
  });
}

function openRoom(roomId) {
  currentRoomId = roomId;
  const room = rooms.get(roomId);
  roomTitle.textContent = room ? room.name : `Комната ${roomId}`;
  roomMeta.textContent = room ? room.meta : "Общий чат";
  emptyState.classList.add("hidden");
  composer.classList.remove("hidden");
  renderMessages(roomId);
  ensureMicOn();
}

function leaveRoomView() {
  currentRoomId = null;
  roomTitle.textContent = "Выберите комнату";
  roomMeta.textContent = "Здесь появятся сообщения и голосовой чат";
  emptyState.classList.remove("hidden");
  composer.classList.add("hidden");
  messageList.innerHTML = "";
  stopMic();
}

async function refreshUsers() {
  const data = await fetchJson("/users");
  renderUsers(data.users);
}

function connectWebSocket() {
  if (socket) {
    socket.close();
  }
  const wsUrl = apiBase().replace("http", "ws");
  socket = new WebSocket(`${wsUrl}/ws?user=${encodeURIComponent(currentUser)}`);
  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "status") {
      refreshUsers();
    }
    if (payload.type === "room_created") {
      rooms.set(payload.room_id, {
        id: payload.room_id,
        name: payload.name,
        meta: "Создана в системе",
      });
      renderRooms();
    }
    if (payload.type === "invite") {
      addInvite(payload);
    }
    if (payload.type === "invite_response") {
      showToast(`Ответ на приглашение: ${payload.status}`);
    }
    if (payload.type === "message") {
      const list = messagesByRoom.get(payload.room_id) || [];
      list.push(payload);
      messagesByRoom.set(payload.room_id, list);
      if (payload.room_id === currentRoomId) {
        renderMessages(payload.room_id);
      }
    }
  });
}

function addInvite(payload) {
  const expiresAt = Date.now() + 5 * 60 * 1000;
  const invite = {
    id: payload.invite_id,
    from: payload.from,
    roomId: payload.room_id,
    roomName: rooms.get(payload.room_id)?.name || `Комната ${payload.room_id.slice(0, 8)}`,
    expiresAt,
  };
  invites.set(invite.id, invite);
  renderInvites();
  setTimeout(() => {
    if (invites.has(invite.id)) {
      invites.delete(invite.id);
      renderInvites();
      showToast("Приглашение истекло (5 минут)");
    }
  }, 5 * 60 * 1000);
}

async function respondInvite(inviteId, accepted) {
  const route = accepted ? "accept" : "decline";
  await fetchJson(`/invites/${inviteId}/${route}`, { method: "POST" });
  const invite = invites.get(inviteId);
  if (accepted && invite) {
    rooms.set(invite.roomId, {
      id: invite.roomId,
      name: invite.roomName,
      meta: `Приглашение от ${invite.from}`,
    });
    renderRooms();
  }
  invites.delete(inviteId);
  renderInvites();
}

async function sendInvite(roomId) {
  const recipient = prompt("Введите имя пользователя для приглашения:");
  if (!recipient) {
    return;
  }
  await fetchJson("/invites", {
    method: "POST",
    body: JSON.stringify({ sender: currentUser, recipient, room_id: roomId }),
  });
  showToast(`Приглашение отправлено: ${recipient}`);
}

async function sendMessage() {
  if (!currentRoomId) {
    showToast("Сначала выберите комнату");
    return;
  }
  const content = messageInput.value.trim();
  const attachments = await readFiles(fileInput.files);
  if (!content && attachments.length === 0) {
    showToast("Добавьте сообщение или вложение");
    return;
  }
  await fetchJson(`/rooms/${currentRoomId}/messages`, {
    method: "POST",
    body: JSON.stringify({ sender: currentUser, content, attachments }),
  });
  messageInput.value = "";
  fileInput.value = "";
}

function readFiles(files) {
  const list = Array.from(files || []);
  return Promise.all(
    list.map((file) =>
      new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = reader.result;
          const dataBase64 = result.split(",")[1];
          resolve({ name: file.name, mime_type: file.type || "application/octet-stream", data_base64: dataBase64 });
        };
        reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
        reader.readAsDataURL(file);
      })
    )
  );
}

function setupEmojiBar() {
  emojiBar.innerHTML = "";
  emojiList.forEach((emoji) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = emoji;
    button.addEventListener("click", () => {
      messageInput.value += emoji;
      messageInput.focus();
    });
    emojiBar.appendChild(button);
  });
}

async function setupAudioDevices() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const audioInputs = devices.filter((device) => device.kind === "audioinput");
  micSelect.innerHTML = "";
  audioInputs.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = device.label || `Микрофон ${micSelect.length + 1}`;
    micSelect.appendChild(option);
  });
}

async function ensureMicOn() {
  try {
    await startMic();
  } catch (error) {
    showToast("Не удалось включить микрофон");
  }
}

async function startMic() {
  if (micStream) {
    stopMic();
  }
  const deviceId = micSelect.value ? { exact: micSelect.value } : undefined;
  micStream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId } });
  micEnabled = true;
  micIndicator.classList.add("online");
  micLabel.textContent = "Микрофон активен";
  toggleMicButton.textContent = "Выключить микрофон";
  startMeter();
}

function stopMic() {
  if (micStream) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
  }
  micEnabled = false;
  micIndicator.classList.remove("online");
  micLabel.textContent = "Микрофон выключен";
  toggleMicButton.textContent = "Включить микрофон";
  stopMeter();
}

function startMeter() {
  if (!micStream) return;
  if (!audioContext) {
    audioContext = new AudioContext();
  }
  const source = audioContext.createMediaStreamSource(micStream);
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 256;
  source.connect(analyser);
  const dataArray = new Uint8Array(analyser.frequencyBinCount);

  const update = () => {
    analyser.getByteFrequencyData(dataArray);
    const volume = dataArray.reduce((sum, value) => sum + value, 0) / dataArray.length;
    const level = Math.min(100, Math.round((volume / 255) * 100));
    micMeter.style.width = `${level}%`;
    micAnimation = requestAnimationFrame(update);
  };
  update();
}

function stopMeter() {
  if (micAnimation) {
    cancelAnimationFrame(micAnimation);
  }
  micMeter.style.width = "0%";
}

async function toggleMic() {
  if (micEnabled) {
    stopMic();
  } else if (currentRoomId) {
    await startMic();
  }
}

async function shareScreen() {
  if (screenStream) {
    screenStream.getTracks().forEach((track) => track.stop());
    screenStream = null;
    screenStatus.textContent = "Демонстрация экрана остановлена";
    shareScreenButton.textContent = "Демонстрация экрана";
    return;
  }
  try {
    screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    screenStatus.textContent = "Экран транслируется";
    shareScreenButton.textContent = "Остановить демонстрацию";
    screenStream.getVideoTracks()[0].addEventListener("ended", () => {
      screenStream = null;
      screenStatus.textContent = "Демонстрация экрана остановлена";
      shareScreenButton.textContent = "Демонстрация экрана";
    });
  } catch (error) {
    showToast("Не удалось начать демонстрацию экрана");
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  try {
    await fetchJson("/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    currentUser = username;
    setView(true);
    await refreshUsers();
    connectWebSocket();
    showToast(`Здравствуйте, ${username}!`);
  } catch (error) {
    showToast(error.message);
  }
});

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = document.getElementById("registerUsername").value.trim();
  const password = document.getElementById("registerPassword").value;
  try {
    await fetchJson("/register", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    showToast("Регистрация успешна, теперь войдите");
  } catch (error) {
    showToast(error.message);
  }
});

roomForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = roomNameInput.value.trim();
  if (!name) {
    return;
  }
  try {
    const result = await fetchJson("/rooms", {
      method: "POST",
      body: JSON.stringify({ name, owner: currentUser, members: [] }),
    });
    rooms.set(result.room_id, { id: result.room_id, name, meta: "Создана вами" });
    renderRooms();
    if (roomInviteInput.value.trim()) {
      await fetchJson("/invites", {
        method: "POST",
        body: JSON.stringify({ sender: currentUser, recipient: roomInviteInput.value.trim(), room_id: result.room_id }),
      });
      showToast("Приглашение отправлено");
    }
    roomNameInput.value = "";
    roomInviteInput.value = "";
  } catch (error) {
    showToast(error.message);
  }
});

sendMessageButton.addEventListener("click", () => {
  sendMessage().catch((error) => showToast(error.message));
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage().catch((error) => showToast(error.message));
  }
});

backToRooms.addEventListener("click", () => {
  leaveRoomView();
});

micSelect.addEventListener("change", () => {
  if (currentRoomId && micEnabled) {
    startMic().catch(() => showToast("Не удалось переключить микрофон"));
  }
});

toggleMicButton.addEventListener("click", () => {
  toggleMic().catch(() => showToast("Не удалось изменить состояние микрофона"));
});

shareScreenButton.addEventListener("click", () => {
  shareScreen();
});

setupEmojiBar();
setView(false);
composer.classList.add("hidden");
setInterval(() => {
  if (invites.size > 0) {
    renderInvites();
  }
}, 30000);

navigator.mediaDevices.addEventListener("devicechange", () => {
  setupAudioDevices();
});

setupAudioDevices().catch(() => {
  micSelect.innerHTML = "<option>Нет доступа к микрофону</option>";
});
