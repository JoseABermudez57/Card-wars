/*
 * Cliente web del POC. Es un cliente "tonto": envía intenciones y dibuja el
 * estado que manda el servidor. NO calcula reglas (eso hará también Unity).
 *
 * Bloques:
 *   1. Red: sobre del protocolo, join/reconexión, seq.
 *   2. Render: dibuja el snapshot `state` (la verdad) + anima los `events`.
 *   3. Acciones: play_card / attack con action_id y expected_turn.
 *   4. Cámara: frames al servidor con UN frame en vuelo como máximo.
 */
"use strict";

const PROTOCOL_VERSION = 1;
const STORAGE_KEY = "card_ar_poc.session";
const FRAME_INTERVAL_MS = 350;   // ~3 fps como máximo
const FRAME_TIMEOUT_MS = 3000;   // si no llega respuesta, se da el frame por perdido
const FRAME_WIDTH = 640;         // suficiente para ArUco y ligero para la red
const STABLE_DETECTIONS = 2;     // frames seguidos con la misma carta antes de proponerla
const ACTION_TIMEOUT_MS = 5000;

// model_key -> representación visual. Hoy un emoji; en Unity, un prefab/Addressable.
const ASSETS = { dragon: "🐉", warrior: "⚔️", mage: "🧙" };

const app = {
  socket: null,
  playerId: null,
  catalog: {},
  visionAvailable: false,
  state: null,
  lastSeq: -1,
  pendingActionId: null,
  pendingTimer: null,
  log: [],
  detected: null,
  camera: { stream: null, inFlight: false, inFlightSince: 0, frameId: 0,
            photoFrameId: null, timer: null, lastCard: null, streak: 0 },
};

const $ = (sel) => document.querySelector(sel);
const canvas = document.createElement("canvas");
const ctx = canvas.getContext("2d");

// ------------------------------------------------------------------ utilidades
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();   // solo en HTTPS
  const b = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

function loadSession() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; } catch { return {}; }
}
function saveSession(session) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(session)); } catch { /* modo privado */ }
}

let toastTimer = null;
function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3000);
}

// --------------------------------------------------------------------- 1. red
function send(type, payload = {}, actionId = null) {
  const msg = { v: PROTOCOL_VERSION, type, payload };
  if (actionId) msg.action_id = actionId;
  app.socket.emit("msg", msg);
}

function connect() {
  app.socket = io();   // reconexión automática incluida
  app.socket.on("connect", () => {
    setConnected(true);
    const session = loadSession();
    if (session.name) join(session.name, session.token);   // reconexión transparente
    else showJoin();
  });
  app.socket.on("disconnect", () => setConnected(false));
  app.socket.on("msg", onMessage);
}

function join(name, token) {
  send("join", { name, session_token: token || undefined });
}

function onMessage(msg) {
  const p = msg.payload || {};
  switch (msg.type) {
    case "welcome":
      app.playerId = p.player_id;
      app.visionAvailable = p.vision_available;
      app.catalog = Object.fromEntries(p.catalog.cards.map((c) => [c.card_id, c]));
      app.lastSeq = -1;   // el servidor pudo reiniciarse: su seq vuelve a empezar
      saveSession({ ...loadSession(), token: p.session_token });
      $("#join-screen").hidden = true;
      $("#game").hidden = false;
      break;
    case "state_update":
      if (msg.seq <= app.lastSeq) return;          // viejo o duplicado: se ignora
      applyState(msg.seq, p.state, p.events || []);
      break;
    case "state_sync":
      applyState(msg.seq, p.state, []);            // la verdad del servidor, sin animar
      break;
    case "card_detected":
      onDetection(p);
      break;
    case "error":
      onError(p, msg.action_id);
      break;
  }
}

function onError(p, actionId) {
  if (actionId && actionId === app.pendingActionId) clearPending();
  if (p.code === "game_full") {
    showJoin("La partida está llena. Espera a que termine.");
    return;
  }
  if (p.code === "vision_unavailable") app.visionAvailable = false;
  app.camera.inFlight = false;
  toast(p.message);
  render();
}

function applyState(seq, state, events) {
  const prev = app.state;
  app.lastSeq = seq;
  app.state = state;
  clearPending();
  if (!canPlayCard()) clearDetection();
  for (const ev of events) addLog(describe(ev, prev, state));
  render();
  animate(events);
}

// ------------------------------------------------------------------- helpers de estado
const me = () => app.state?.players.find((p) => p.player_id === app.playerId);
const rival = () => app.state?.players.find((p) => p.player_id !== app.playerId);
const isMyTurn = () => app.state?.status === "in_progress" &&
                       app.state.current_player_id === app.playerId;
const canPlayCard = () => isMyTurn() && me()?.field.length === 0 && !app.pendingActionId;
const canAttack = () => isMyTurn() && me()?.field.length > 0 && !app.pendingActionId;

// ------------------------------------------------------------------ 2. render
function setConnected(ok) {
  $("#conn-dot").classList.toggle("ok", ok);
  if (!ok) $("#status-text").textContent = "Reconectando…";
}

function showJoin(error = "") {
  $("#join-screen").hidden = false;
  $("#join-error").textContent = error;
  $("#name-input").value = loadSession().name || "";
}

function render() {
  const s = app.state;
  if (!s) return;
  const my = me();
  const other = rival();

  let status;
  if (s.status === "waiting") status = "Esperando rival…";
  else if (s.status === "finished") status = "Partida terminada";
  else status = isMyTurn() ? `Tu turno · turno ${s.turn_number}`
                           : `Turno de ${escapeHtml(other?.name ?? "rival")} · turno ${s.turn_number}`;
  $("#status-text").innerHTML = status;

  renderPlayer($("#rival-panel"), other, false);
  renderPlayer($("#me-panel"), my, true);
  renderHand(my);

  const attackBtn = $("#attack-btn");
  attackBtn.hidden = !(my && my.field.length > 0 && s.status === "in_progress");
  attackBtn.disabled = !canAttack();

  let hint = "";
  if (s.status === "in_progress") {
    if (!isMyTurn()) hint = "Espera tu turno.";
    else if (my.field.length > 0) hint = "Tienes criatura en mesa: ataca con ella.";
    else hint = "Juega una carta: tócala o enséñala a la cámara.";
  }
  $("#turn-hint").textContent = hint;

  renderLog();
  renderCamera();
  renderGameOver();
}

function creatureHtml(c) {
  const pct = Math.max(0, (c.hp / c.max_hp) * 100);
  return `
    <div class="creature" data-uid="${c.uid}">
      <span class="art">${ASSETS[c.model_key] ?? "❔"}</span>
      <div class="creature-info">
        <b>${escapeHtml(c.name)}</b>
        <span class="stats">⚔️ ${c.attack} · ❤️ ${c.hp}/${c.max_hp}</span>
        <div class="bar small"><div class="fill" style="width:${pct}%"></div></div>
      </div>
    </div>`;
}

function renderPlayer(el, p, isMe) {
  if (!p) {
    el.removeAttribute("data-player-id");
    el.classList.remove("active");
    el.innerHTML = `<div class="empty">Esperando rival…
      <small>Abre <b>${escapeHtml(location.origin)}</b> en otro teléfono</small></div>`;
    return;
  }
  const active = app.state.current_player_id === p.player_id;
  const creature = p.field[0];
  el.dataset.playerId = p.player_id;
  el.classList.toggle("active", active);
  el.innerHTML = `
    <div class="player-head">
      <span class="name">${escapeHtml(p.name)}${isMe ? " (tú)" : ""}</span>
      ${p.connected ? "" : '<span class="badge warn">desconectado</span>'}
      ${active ? `<span class="badge turn">${isMe ? "tu turno" : "su turno"}</span>` : ""}
    </div>
    <div class="life">
      <div class="bar"><div class="fill" style="width:${Math.max(0, Math.min(100, (100 * p.life) / (p.max_life || 100)))}%"></div></div>
      <span class="life-num">❤️ ${p.life}/${p.max_life ?? "?"}</span>
    </div>
    <div class="field">${creature ? creatureHtml(creature) : '<div class="slot-empty">Sin criatura</div>'}</div>
    <div class="meta">🂠 ${p.hand_count} en mano · 📚 ${p.deck_count ?? 0} en mazo · 🪦 ${p.discard.length} descartadas</div>`;
}

function renderHand(my) {
  const hand = my?.hand ?? [];
  const enabled = canPlayCard();
  $("#hand").innerHTML = hand.length === 0
    ? '<p class="hint">Sin cartas en la mano.</p>'
    : hand.map((id) => {
        const c = app.catalog[id];
        const highlighted = app.detected?.card_id === id ? " detected" : "";
        return `<button class="card${highlighted}" data-card-id="${id}" ${enabled ? "" : "disabled"}>
                  <span class="art">${ASSETS[c.model_key] ?? "❔"}</span>
                  <b>${escapeHtml(c.name)}</b>
                  <span class="stats">⚔️ ${c.attack} · ❤️ ${c.max_hp}</span>
                </button>`;
      }).join("");
}

function renderGameOver() {
  const s = app.state;
  const screen = $("#gameover-screen");
  if (s.status !== "finished") { screen.hidden = true; return; }
  screen.hidden = false;
  const won = s.winner_id === app.playerId;
  $("#gameover-title").textContent = s.winner_id == null ? "Empate" : won ? "¡Victoria! 🏆" : "Derrota 💀";
  const loser = s.players.find((p) => p.eliminated);
  $("#gameover-reason").textContent = loser ? `${loser.name} quedó eliminado.` : "";
  const btn = $("#rematch-btn");
  const rivalGone = s.players.length < s.max_players;
  const waiting = me()?.wants_rematch;
  btn.disabled = rivalGone || !!waiting;
  btn.textContent = rivalGone ? "Tu rival se fue · esperando jugador nuevo…"
                  : waiting ? "Esperando al rival…" : "🔁 Revancha";
}

// ----- registro de combate (texto) + animaciones
function addLog(text) {
  if (!text) return;
  app.log.unshift(text);
  app.log.length = Math.min(app.log.length, 30);
}

function renderLog() {
  $("#battle-log").innerHTML = app.log.slice(0, 6)
    .map((t, i) => `<div class="log-line${i === 0 ? " latest" : ""}">${t}</div>`).join("");
}

function describe(ev, prev, next) {
  const players = [...(prev?.players ?? []), ...next.players];
  const name = (id) => escapeHtml(players.find((p) => p.player_id === id)?.name ?? "?");
  const creatures = players.flatMap((p) => p.field);
  const cname = (uid) => escapeHtml(creatures.find((c) => c.uid === uid)?.name ?? "criatura");
  const e = ev.payload;
  switch (ev.type) {
    case "player_joined": return `👋 ${name(e.player_id)} se unió`;
    case "game_started": return `🎬 ¡Empieza la partida! Abre ${name(e.current_player_id)}`;
    case "card_played": return `${e.source === "camera" ? "📷" : "👆"} ${name(e.player_id)} juega ${escapeHtml(e.card.name)}`;
    case "creature_damaged": return `💥 ${cname(e.attacker_uid)} golpea a ${cname(e.target_uid)}: −${e.damage} (le quedan ${e.remaining_hp})`;
    case "creature_destroyed": return `🪦 ${cname(e.uid)} de ${name(e.owner_id)} fue destruido`;
    case "player_damaged": return `🩸 ${cname(e.attacker_uid)} golpea a ${name(e.player_id)}: −${e.damage} ❤️ (le quedan ${e.remaining_life})`;
    case "turn_changed": return `⏭️ Turno ${e.turn_number}: ${name(e.current_player_id)}`;
    case "player_eliminated": {
      const why = { life: "sin vida", no_creatures: "sin criaturas ni cartas", abandon: "por abandono" }[e.reason] ?? e.reason;
      return `☠️ ${name(e.player_id)} eliminado (${why})`;
    }
    case "game_over": return e.winner_id ? `🏆 Gana ${name(e.winner_id)}` : "🤝 Empate";
    case "player_disconnected": return `📴 ${name(e.player_id)} se desconectó`;
    case "player_reconnected": return `📶 ${name(e.player_id)} volvió`;
    case "player_left": return `🚪 ${name(e.player_id)} salió`;
    case "rematch_requested": return `🔁 ${name(e.player_id)} quiere revancha`;
    // La carta solo viene para quien roba; el rival recibe card: null.
    case "card_drawn": return e.card
      ? `🃏 Robas ${escapeHtml(e.card.name)} (quedan ${e.deck_count} en el mazo)`
      : `🃏 ${name(e.player_id)} roba una carta`;
    default: return null;
  }
}

function flash(el, cls, label) {
  if (!el) return;
  el.classList.remove(cls);
  void el.offsetWidth;            // reinicia la animación CSS
  el.classList.add(cls);
  if (label) {
    const f = document.createElement("span");
    f.className = "float";
    f.textContent = label;
    el.appendChild(f);
    setTimeout(() => f.remove(), 1000);
  }
}

// Los eventos disparan animaciones; en Unity serían animaciones de los modelos 3D.
function animate(events) {
  for (const { type, payload: e } of events) {
    if (type === "card_played") flash(document.querySelector(`[data-uid="${e.card.uid}"]`), "enter");
    if (type === "creature_damaged") flash(document.querySelector(`[data-uid="${e.target_uid}"]`), "hit", `−${e.damage}`);
    if (type === "player_damaged") flash(document.querySelector(`[data-player-id="${e.player_id}"] .life`), "hit", `−${e.damage}`);
  }
}

// ------------------------------------------------------------------ 3. acciones
function startPending() {
  const id = uuid();
  app.pendingActionId = id;
  clearTimeout(app.pendingTimer);
  app.pendingTimer = setTimeout(() => {   // respuesta perdida: pedimos la verdad
    app.pendingActionId = null;
    send("sync");
  }, ACTION_TIMEOUT_MS);
  return id;
}

function clearPending() {
  app.pendingActionId = null;
  clearTimeout(app.pendingTimer);
}

function playCard(cardId, source) {
  if (!canPlayCard()) return;
  const actionId = startPending();
  send("play_card", { card_id: cardId, expected_turn: app.state.turn_number, source }, actionId);
  clearDetection();
  render();
}

function attack() {
  if (!canAttack()) return;
  const actionId = startPending();
  send("attack", { expected_turn: app.state.turn_number }, actionId);
  render();
}

// -------------------------------------------------------------------- 4. cámara
const video = $("#video");

function wantFrames() {
  return app.camera.stream && app.visionAvailable && canPlayCard();
}

async function toggleCamera() {
  if (app.camera.stream) { stopCamera(); return; }
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    toast("La cámara en vivo necesita HTTPS. Usa el botón Foto.");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    app.camera.stream = stream;
    video.srcObject = stream;
    video.hidden = false;
    await video.play();
    scheduleFrame();
  } catch (err) {
    toast(`No se pudo abrir la cámara: ${err.message}`);
    stopCamera();
  }
  render();
}

function stopCamera() {
  const cam = app.camera;
  cam.stream?.getTracks().forEach((t) => t.stop());
  cam.stream = null;
  clearTimeout(cam.timer);
  video.srcObject = null;
  video.hidden = true;
  render();
}

function scheduleFrame() {
  clearTimeout(app.camera.timer);
  app.camera.timer = setTimeout(captureLoop, FRAME_INTERVAL_MS);
}

function captureLoop() {
  const cam = app.camera;
  if (!cam.stream) return;
  if (cam.inFlight && Date.now() - cam.inFlightSince > FRAME_TIMEOUT_MS) cam.inFlight = false;
  // Control de flujo: solo si puedo jugar, y nunca con un frame ya en camino.
  if (!cam.inFlight && wantFrames() && video.readyState >= 2) {
    sendFrame(video, video.videoWidth, video.videoHeight);
  }
  scheduleFrame();
}

function sendFrame(source, w, h) {
  if (!w || !h) return null;
  const scale = Math.min(1, FRAME_WIDTH / w);
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  const cam = app.camera;
  cam.frameId += 1;
  cam.inFlight = true;
  cam.inFlightSince = Date.now();
  send("frame", { image: canvas.toDataURL("image/jpeg", 0.7), frame_id: cam.frameId });
  return cam.frameId;
}

// Respaldo sin HTTPS: <input capture> abre la cámara nativa y sube una foto.
function onPhotoSelected(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  if (!canPlayCard()) { toast("Ahora no puedes jugar una carta."); return; }
  const img = new Image();
  const url = URL.createObjectURL(file);
  img.onload = () => {
    app.camera.photoFrameId = sendFrame(img, img.naturalWidth, img.naturalHeight);
    URL.revokeObjectURL(url);
  };
  img.onerror = () => { toast("No se pudo leer la imagen"); URL.revokeObjectURL(url); };
  img.src = url;
}

function onDetection(p) {
  const cam = app.camera;
  cam.inFlight = false;
  const fromPhoto = p.frame_id === cam.photoFrameId;
  const hand = me()?.hand ?? [];
  const playable = p.cards.filter((c) => hand.includes(c.card_id));

  if (playable.length !== 1) {
    cam.lastCard = null;
    cam.streak = 0;
    if (fromPhoto) {
      toast(playable.length > 1 ? "Se ven varias cartas: enseña solo una."
          : p.cards.length ? "Esa carta no está en tu mano." : "No se detectó ninguna carta.");
    }
    return;
  }
  // Estabilidad: la misma carta en N frames seguidos evita falsos positivos.
  const card = playable[0];
  if (card.card_id === cam.lastCard) cam.streak += 1;
  else { cam.lastCard = card.card_id; cam.streak = 1; }
  if (fromPhoto || cam.streak >= STABLE_DETECTIONS) {
    app.detected = card;
    render();
  }
}

function clearDetection() {
  app.detected = null;
  app.camera.lastCard = null;
  app.camera.streak = 0;
}

function renderCamera() {
  const cam = app.camera;
  $("#camera-btn").textContent = cam.stream ? "⏹️ Detener cámara" : "📷 Cámara en vivo";
  $("#camera-btn").disabled = !app.visionAvailable;
  $("#photo-btn").classList.toggle("disabled", !app.visionAvailable || !canPlayCard());

  let hint;
  if (!app.visionAvailable) hint = "El servidor no tiene la visión (OpenCV) activa.";
  else if (!window.isSecureContext) hint = "Sin HTTPS la cámara en vivo no está disponible: usa Foto.";
  else if (!cam.stream) hint = "Activa la cámara y enseña una carta con su marcador.";
  else if (!canPlayCard()) hint = "Escaneo en pausa: solo se escanea cuando puedes jugar una carta.";
  else hint = "Apunta a una carta…";
  $("#camera-hint").textContent = hint;

  const box = $("#detection");
  const d = app.detected;
  box.hidden = !(d && canPlayCard());
  if (!box.hidden) {
    box.innerHTML = `
      <span class="art">${ASSETS[d.model_key] ?? "❔"}</span>
      <span>Detectado: <b>${escapeHtml(d.name)}</b></span>
      <button class="btn primary" data-action="play-detected">Jugar</button>
      <button class="btn ghost" data-action="dismiss-detected" aria-label="Descartar">✕</button>`;
  }
}

// ------------------------------------------------------------------- eventos UI
$("#join-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const name = $("#name-input").value.trim();
  if (!name) return;
  const session = loadSession();
  saveSession({ ...session, name });
  join(name, session.token);
});

$("#hand").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-card-id]");
  if (btn) playCard(btn.dataset.cardId, "ui");
});

$("#attack-btn").addEventListener("click", attack);
$("#rematch-btn").addEventListener("click", () => send("rematch"));
$("#camera-btn").addEventListener("click", toggleCamera);
$("#photo-input").addEventListener("change", onPhotoSelected);

$("#detection").addEventListener("click", (e) => {
  const action = e.target.closest("[data-action]")?.dataset.action;
  if (action === "play-detected" && app.detected) playCard(app.detected.card_id, "camera");
  if (action === "dismiss-detected") { clearDetection(); render(); }
});

connect();
