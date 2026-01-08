const authSection = document.getElementById("auth-section");
const dashboard = document.getElementById("dashboard");
const chatView = document.getElementById("chat-view");
const authMessage = document.getElementById("auth-message");
const statusMessage = document.getElementById("status-message");
const roomList = document.getElementById("room-list");
const userList = document.getElementById("user-list");
const inviteList = document.getElementById("invite-list");
const currentUserBadge = document.getElementById("current-user");
const chatTitle = document.getElementById("chat-title");
const chatMessages = document.getElementById("chat-messages");
const messageInput = document.getElementById("message-input");
const fileInput = document.getElementById("file-input");
const emojiBar = document.getElementById("emoji-bar");
const roomInviteList = document.getElementById("room-invite-list");
const voicePanel = document.getElementById("voice-panel");
const audioDeviceSelect = document.getElementById("audio-device");
const micLevel = document.getElementById("mic-level");
const voiceStatus = document.getElementById("voice-status");
const remoteMedia = document.getElementById("remote-media");

const EMOJIS = ["😀", "😂", "😍", "👍", "🎉", "🙏", "🔥", "💬", "🎧", "🎤"];
let state = {
  username: null,
  token: null,
  rooms: [],
  users: [],
  invites: [],
  currentRoom: null,
  websocket: null,
  peerConnections: {},
  localStream: null,
  screenStream: null,
  audioAnalyser: null,
  audioLevelTimer: null,
};

function setMessage(target, text, isError = false) {
  target.textContent = text;
  target.style.color = isError ? "#d7263d" : "#2f6fed";
}

function saveSession() {
  localStorage.setItem("vds-user", JSON.stringify({ username: state.username, token: state.token }));
}

function loadSession() {
  const raw = localStorage.getItem("vds-user");
  if (!raw) return;
  try {
    const parsed = JSON.parse(raw);
    state.username = parsed.username;
    state.token = parsed.token;
  } catch {
    return;
  }
}

function clearSession() {
  localStorage.removeItem("vds-user");
  state.username = null;
  state.token = null;
}

async function apiFetch(path, options = {}) {
  const headers = options.headers || {};
  if (state.token) {
    headers["X-Auth-Token"] = state.token;
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || response.statusText);
  }
  return response.json();
}

function showDashboard() {
  authSection.classList.add("hidden");
  chatView.classList.add("hidden");
  dashboard.classList.remove("hidden");
  currentUserBadge.textContent = state.username;
}

function showAuth() {
  dashboard.classList.add("hidden");
  chatView.classList.add("hidden");
  authSection.classList.remove("hidden");
}

function showChatView() {
  dashboard.classList.add("hidden");
  chatView.classList.remove("hidden");
}

function renderUsers() {
  userList.innerHTML = "";
  state.users.forEach((user) => {
    const li = document.createElement("li");
    li.className = `list-item ${user.online ? "online" : "offline"}`;
    li.innerHTML = `
      <span>${user.username}</span>
      <span>${user.online ? "Онлайн" : "Оффлайн"}</span>
    `;
    userList.appendChild(li);
  });
}

function renderRooms() {
  roomList.innerHTML = "";
  state.rooms.forEach((room) => {
    const li = document.createElement("li");
    li.className = "list-item";
    const button = document.createElement("button");
    button.className = "secondary";
    button.textContent = "Открыть";
    button.addEventListener("click", () => enterRoom(room));
    li.innerHTML = `
      <div>
        <strong>${room.name}</strong>
        <div class="meta">${room.room_type === "voice" ? "Голосовой" : "Текстовый"}</div>
      </div>
    `;
    li.appendChild(button);
    roomList.appendChild(li);
  });
}

function renderInvites() {
  inviteList.innerHTML = "";
  state.invites.forEach((invite) => {
    const li = document.createElement("li");
    li.className = "list-item";
    li.innerHTML = `
      <div>
        <div><strong>${invite.from}</strong> приглашает в комнату</div>
        <div class="meta">ID комнаты: ${invite.room_id}</div>
      </div>
    `;
    const actions = document.createElement("div");
    const accept = document.createElement("button");
    accept.textContent = "Принять";
    accept.addEventListener("click", () => respondInvite(invite.invite_id, true));
    const decline = document.createElement("button");
    decline.className = "secondary";
    decline.textContent = "Отказать";
    decline.addEventListener("click", () => respondInvite(invite.invite_id, false));
    actions.appendChild(accept);
    actions.appendChild(decline);
    li.appendChild(actions);
    inviteList.appendChild(li);
  });
}

function renderRoomInviteList() {
  roomInviteList.innerHTML = "";
  if (!state.currentRoom) return;
  const candidates = state.users.filter(
    (user) => user.username !== state.username && user.online
  );
  if (candidates.length === 0) {
    const li = document.createElement("li");
    li.className = "list-item offline";
    li.textContent = "Нет онлайн пользователей для приглашения.";
    roomInviteList.appendChild(li);
    return;
  }
  candidates.forEach((user) => {
    const li = document.createElement("li");
    li.className = "list-item online";
    const button = document.createElement("button");
    button.textContent = "Пригласить";
    button.addEventListener("click", () => createInvite(user.username));
    li.innerHTML = `<span>${user.username}</span>`;
    li.appendChild(button);
    roomInviteList.appendChild(li);
  });
}

async function createInvite(recipient) {
  if (!state.currentRoom) return;
  try {
    await apiFetch("/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sender: state.username,
        recipient,
        room_id: state.currentRoom.id,
      }),
    });
    setMessage(statusMessage, `Приглашение отправлено пользователю ${recipient}.`);
  } catch (error) {
    setMessage(statusMessage, error.message, true);
  }
}

async function respondInvite(inviteId, accepted) {
  try {
    await apiFetch(`/invites/${inviteId}/${accepted ? "accept" : "decline"}`, {
      method: "POST",
    });
    state.invites = state.invites.filter((invite) => invite.invite_id !== inviteId);
    renderInvites();
    await refreshRooms();
  } catch (error) {
    setMessage(statusMessage, error.message, true);
  }
}

async function refreshUsers() {
  const data = await apiFetch("/users");
  state.users = data.users;
  renderUsers();
  renderRoomInviteList();
}

async function refreshRooms() {
  const data = await apiFetch(`/rooms?user=${encodeURIComponent(state.username)}`);
  state.rooms = data.rooms;
  renderRooms();
}

async function initDashboard() {
  await refreshUsers();
  await refreshRooms();
  renderInvites();
}

async function registerUser(username, password) {
  await apiFetch("/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

async function loginUser(username, password) {
  const data = await apiFetch("/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  state.username = username;
  state.token = data.token;
  saveSession();
  await setupWebSocket();
  showDashboard();
  await initDashboard();
}

async function logoutUser() {
  if (!state.token) return;
  await apiFetch("/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: state.token }),
  });
  if (state.websocket) {
    state.websocket.close();
  }
  clearSession();
  showAuth();
}

async function createRoom(name, roomType) {
  await apiFetch("/rooms", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, owner: state.username, room_type: roomType, members: [] }),
  });
  await refreshRooms();
}

function appendMessage(message) {
  const div = document.createElement("div");
  div.className = "message-item";
  const time = new Date(message.created_at).toLocaleString();
  div.innerHTML = `
    <div class="meta">${message.sender} • ${time}</div>
    <div>${message.content || ""}</div>
  `;
  if (message.attachments && message.attachments.length) {
    message.attachments.forEach((attachment) => {
      const wrapper = document.createElement("div");
      if (attachment.mime_type.startsWith("image/")) {
        const img = document.createElement("img");
        img.src = `data:${attachment.mime_type};base64,${attachment.data_base64}`;
        img.alt = attachment.name;
        img.style.maxWidth = "240px";
        wrapper.appendChild(img);
      } else {
        const link = document.createElement("a");
        link.href = `data:${attachment.mime_type};base64,${attachment.data_base64}`;
        link.download = attachment.name;
        link.textContent = `Скачать ${attachment.name}`;
        wrapper.appendChild(link);
      }
      div.appendChild(wrapper);
    });
  }
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function loadMessages(roomId) {
  chatMessages.innerHTML = "";
  const data = await apiFetch(`/rooms/${roomId}/messages`);
  data.messages.forEach(appendMessage);
}

async function enterRoom(room) {
  state.currentRoom = room;
  chatTitle.textContent = `${room.name} (${room.room_type === "voice" ? "Голосовой" : "Текстовый"})`;
  showChatView();
  await loadMessages(room.id);
  renderRoomInviteList();
  if (room.room_type === "voice") {
    voicePanel.classList.remove("hidden");
    await startVoiceChat(room);
  } else {
    voicePanel.classList.add("hidden");
    await stopVoiceChat();
  }
}

async function sendMessage(content, attachments) {
  if (!state.currentRoom) return;
  await apiFetch(`/rooms/${state.currentRoom.id}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sender: state.username, content, attachments }),
  });
}

function setupEmojiBar() {
  EMOJIS.forEach((emoji) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = emoji;
    button.addEventListener("click", () => {
      messageInput.value += emoji;
    });
    emojiBar.appendChild(button);
  });
}

async function readFiles() {
  const files = Array.from(fileInput.files || []);
  const attachments = [];
  for (const file of files) {
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(new Error("Ошибка чтения файла"));
      reader.readAsDataURL(file);
    });
    attachments.push({
      name: file.name,
      mime_type: file.type || "application/octet-stream",
      data_base64: data,
    });
  }
  return attachments;
}

async function setupWebSocket() {
  if (state.websocket) {
    state.websocket.close();
  }
  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
  state.websocket = new WebSocket(
    `${wsProtocol}://${window.location.host}/ws?user=${encodeURIComponent(state.username)}&token=${encodeURIComponent(
      state.token
    )}`
  );
  state.websocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "status") {
      const user = state.users.find((item) => item.username === data.user);
      if (user) {
        user.online = data.online;
      } else {
        state.users.push({ username: data.user, online: data.online });
      }
      renderUsers();
      renderRoomInviteList();
    }
    if (data.type === "room_created") {
      refreshRooms();
    }
    if (data.type === "invite") {
      state.invites.push({ invite_id: data.invite_id, room_id: data.room_id, from: data.from });
      renderInvites();
    }
    if (data.type === "invite_response") {
      state.invites = state.invites.filter((invite) => invite.invite_id !== data.invite_id);
      renderInvites();
      if (data.status === "accepted") {
        refreshRooms();
      }
    }
    if (data.type === "message" && state.currentRoom && data.room_id === state.currentRoom.id) {
      appendMessage(data);
    }
    if (data.type === "signal") {
      handleSignal(data);
    }
  };
}

async function populateAudioDevices() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  audioDeviceSelect.innerHTML = "";
  devices
    .filter((device) => device.kind === "audioinput")
    .forEach((device) => {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent = device.label || `Микрофон ${audioDeviceSelect.length + 1}`;
      audioDeviceSelect.appendChild(option);
    });
}

async function getLocalStream() {
  const deviceId = audioDeviceSelect.value;
  const constraints = {
    audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    video: false,
  };
  return navigator.mediaDevices.getUserMedia(constraints);
}

function startMicMeter(stream) {
  if (state.audioLevelTimer) {
    clearInterval(state.audioLevelTimer);
  }
  const audioContext = new AudioContext();
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 256;
  const source = audioContext.createMediaStreamSource(stream);
  source.connect(analyser);
  const dataArray = new Uint8Array(analyser.frequencyBinCount);
  state.audioLevelTimer = setInterval(() => {
    analyser.getByteTimeDomainData(dataArray);
    let sum = 0;
    for (const value of dataArray) {
      sum += Math.abs(value - 128);
    }
    const level = Math.min(100, (sum / dataArray.length) * 2);
    micLevel.style.width = `${level}%`;
  }, 100);
}

async function startVoiceChat(room) {
  try {
    await populateAudioDevices();
    state.localStream = await getLocalStream();
    startMicMeter(state.localStream);
    voiceStatus.textContent = "Микрофон включен";
    await connectToRoomMembers(room);
  } catch (error) {
    voiceStatus.textContent = `Ошибка микрофона: ${error.message}`;
  }
}

async function stopVoiceChat() {
  if (state.localStream) {
    state.localStream.getTracks().forEach((track) => track.stop());
    state.localStream = null;
  }
  if (state.screenStream) {
    state.screenStream.getTracks().forEach((track) => track.stop());
    state.screenStream = null;
  }
  Object.values(state.peerConnections).forEach((pc) => pc.close());
  state.peerConnections = {};
  remoteMedia.innerHTML = "";
  if (state.audioLevelTimer) {
    clearInterval(state.audioLevelTimer);
  }
}

async function connectToRoomMembers(room) {
  const roomInfo = await apiFetch(`/rooms/${room.id}`);
  const members = roomInfo.room.members.filter((member) => member !== state.username);
  for (const member of members) {
    if (!state.peerConnections[member]) {
      await createPeerConnection(member, true);
    }
  }
}

async function createPeerConnection(peer, isInitiator) {
  const pc = new RTCPeerConnection();
  state.peerConnections[peer] = pc;

  if (state.localStream) {
    state.localStream.getTracks().forEach((track) => pc.addTrack(track, state.localStream));
  }
  if (state.screenStream) {
    state.screenStream.getTracks().forEach((track) => pc.addTrack(track, state.screenStream));
  }

  pc.onicecandidate = (event) => {
    if (event.candidate) {
      sendSignal(peer, { candidate: event.candidate });
    }
  };

  pc.ontrack = (event) => {
    const stream = event.streams[0];
    let mediaEl = document.getElementById(`remote-${peer}-${event.track.kind}`);
    if (!mediaEl) {
      mediaEl = document.createElement(event.track.kind === "video" ? "video" : "audio");
      mediaEl.id = `remote-${peer}-${event.track.kind}`;
      mediaEl.autoplay = true;
      mediaEl.controls = event.track.kind === "video";
      remoteMedia.appendChild(mediaEl);
    }
    mediaEl.srcObject = stream;
  };

  if (isInitiator) {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    sendSignal(peer, { offer });
  }
}

function sendSignal(peer, data) {
  if (!state.websocket) return;
  state.websocket.send(
    JSON.stringify({
      type: "signal",
      to: peer,
      from: state.username,
      room_id: state.currentRoom?.id,
      data,
    })
  );
}

async function handleSignal(payload) {
  const from = payload.from;
  if (!from || from === state.username) return;
  let pc = state.peerConnections[from];
  if (!pc) {
    await createPeerConnection(from, false);
    pc = state.peerConnections[from];
  }
  if (payload.data.offer) {
    await pc.setRemoteDescription(new RTCSessionDescription(payload.data.offer));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    sendSignal(from, { answer });
  }
  if (payload.data.answer) {
    await pc.setRemoteDescription(new RTCSessionDescription(payload.data.answer));
  }
  if (payload.data.candidate) {
    await pc.addIceCandidate(new RTCIceCandidate(payload.data.candidate));
  }
}

async function startScreenShare() {
  if (!state.currentRoom || state.currentRoom.room_type !== "voice") return;
  try {
    state.screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    Object.values(state.peerConnections).forEach((pc) => {
      state.screenStream.getTracks().forEach((track) => pc.addTrack(track, state.screenStream));
    });
  } catch (error) {
    voiceStatus.textContent = `Ошибка демонстрации экрана: ${error.message}`;
  }
}

function bindEvents() {
  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await loginUser(
        document.getElementById("login-username").value,
        document.getElementById("login-password").value
      );
      setMessage(authMessage, "Успешный вход.");
    } catch (error) {
      setMessage(authMessage, error.message, true);
    }
  });

  document.getElementById("register-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await registerUser(
        document.getElementById("register-username").value,
        document.getElementById("register-password").value
      );
      setMessage(authMessage, "Регистрация успешна. Теперь войдите.");
    } catch (error) {
      setMessage(authMessage, error.message, true);
    }
  });

  document.getElementById("logout-button").addEventListener("click", async () => {
    await logoutUser();
  });

  document.getElementById("create-room-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.getElementById("room-name").value;
    const roomType = document.getElementById("room-type").value;
    try {
      await createRoom(name, roomType);
      event.target.reset();
    } catch (error) {
      setMessage(statusMessage, error.message, true);
    }
  });

  document.getElementById("message-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = messageInput.value.trim();
    if (!content && (!fileInput.files || fileInput.files.length === 0)) {
      return;
    }
    try {
      const attachments = await readFiles();
      await sendMessage(content, attachments);
      messageInput.value = "";
      fileInput.value = "";
    } catch (error) {
      setMessage(statusMessage, error.message, true);
    }
  });

  document.getElementById("back-button").addEventListener("click", async () => {
    await stopVoiceChat();
    state.currentRoom = null;
    showDashboard();
  });

  document.getElementById("share-screen").addEventListener("click", async () => {
    await startScreenShare();
  });

  audioDeviceSelect.addEventListener("change", async () => {
    if (state.currentRoom?.room_type === "voice") {
      await stopVoiceChat();
      await startVoiceChat(state.currentRoom);
    }
  });
}

async function bootstrap() {
  setupEmojiBar();
  bindEvents();
  loadSession();
  if (state.username && state.token) {
    try {
      await setupWebSocket();
      showDashboard();
      await initDashboard();
      setMessage(authMessage, "");
    } catch {
      clearSession();
      showAuth();
    }
  }
}

bootstrap();
