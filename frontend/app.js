/* Telusur — antarmuka. Riwayat di localStorage, server tetap tanpa database.
   Yang ditampilkan hanya pertanyaan dan jawaban naratif. Tidak ada daftar
   sumber, tidak ada tautan, tidak ada jejak proses pencarian. */

const STORAGE_KEY = "telusur.history.v1";
const ACCESS_KEY_STORAGE = "telusur.access.v1";
const MAX_STORED_TURNS = 40;
const HISTORY_SENT_TURNS = 12;

const els = {
  thread: document.getElementById("thread"),
  intro: document.getElementById("intro"),
  composer: document.getElementById("composer"),
  input: document.getElementById("input"),
  send: document.getElementById("send"),
  clear: document.getElementById("clear"),
  status: document.getElementById("status"),
  recent: document.getElementById("recent"),
  toast: document.getElementById("toast"),
  gate: document.getElementById("gate"),
  gateForm: document.getElementById("gate-form"),
  gateInput: document.getElementById("gate-input"),
  pickImage: document.getElementById("pick-image"),
  pickAudio: document.getElementById("pick-audio"),
  pickLive: document.getElementById("pick-live"),
  fileImage: document.getElementById("file-image"),
  fileAudio: document.getElementById("file-audio"),
  level: document.getElementById("level"),
  attachNote: document.getElementById("attach-note"),
};

let turns = loadTurns();
let accessKey = loadAccessKey();
let busy = false;
let gateOpen = false;
let recording = false;
let sttReady = false;

/* ---------------- penyimpanan ---------------- */

function loadTurns() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isTurn) : [];
  } catch {
    return [];
  }
}

function isTurn(t) {
  return !!t && (t.role === "user" || t.role === "assistant") && typeof t.content === "string";
}

function saveTurns() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(turns.slice(-MAX_STORED_TURNS)));
  } catch {
    /* mode privat bisa menolak penulisan. Riwayat tetap jalan di memori. */
  }
}

function loadAccessKey() {
  try {
    return localStorage.getItem(ACCESS_KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

function saveAccessKey(value) {
  try {
    if (value) localStorage.setItem(ACCESS_KEY_STORAGE, value);
    else localStorage.removeItem(ACCESS_KEY_STORAGE);
  } catch {
    /* diabaikan: kunci tetap terpakai selama tab ini terbuka */
  }
}

function requestHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (accessKey) headers["X-Access-Key"] = accessKey;
  return headers;
}

/* ---------------- utilitas kecil ---------------- */

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function setStatus(text, state) {
  els.status.textContent = text;
  els.status.dataset.state = state;
}

function syncComposer() {
  const blocked = busy || gateOpen;
  els.send.disabled = blocked || recording;
  els.pickImage.disabled = blocked || recording;
  els.pickAudio.disabled = blocked || recording;
  els.pickLive.disabled = blocked;
}

function setBusy(value) {
  busy = value;
  document.body.dataset.busy = value ? "true" : "false";
  syncComposer();
}

function showGate(message) {
  gateOpen = true;
  els.gate.hidden = false;
  syncComposer();
  if (message) toast(message);
  els.gateInput.focus();
}

function hideGate() {
  gateOpen = false;
  els.gate.hidden = true;
  syncComposer();
  els.input.focus();
}

/* ---------------- unggahan: gambar dan audio ---------------- */

const MAX_UPLOAD_BYTES = 3 * 1024 * 1024;
const IMAGE_MAX_EDGE = 1280;

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Berkas gagal dibaca."));
    reader.readAsDataURL(file);
  });
}

function dataUrlParts(dataUrl) {
  const comma = dataUrl.indexOf(",");
  if (comma === -1) throw new Error("Berkas tidak terbaca.");

  const head = dataUrl.slice(0, comma);
  const mime = (head.match(/^data:([^;]+)/) || [])[1] || "application/octet-stream";
  return { mime, base64: dataUrl.slice(comma + 1) };
}

function base64Bytes(base64) {
  const padding = (base64.match(/=*$/) || [""])[0].length;
  return Math.floor((base64.length * 3) / 4) - padding;
}

async function downscaleImage(file) {
  const raw = await readFileAsDataURL(file);
  const parts = dataUrlParts(raw);

  if (file.type !== "image/gif" && base64Bytes(parts.base64) <= MAX_UPLOAD_BYTES) {
    return parts;
  }

  const image = await new Promise((resolve, reject) => {
    const node = new Image();
    node.onload = () => resolve(node);
    node.onerror = () => reject(new Error("Gambar tidak bisa dibaca."));
    node.src = raw;
  });

  const scale = Math.min(1, IMAGE_MAX_EDGE / Math.max(image.width, image.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.width * scale));
  canvas.height = Math.max(1, Math.round(image.height * scale));
  canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);

  let quality = 0.85;
  let out = dataUrlParts(canvas.toDataURL("image/jpeg", quality));
  while (base64Bytes(out.base64) > MAX_UPLOAD_BYTES && quality > 0.4) {
    quality -= 0.15;
    out = dataUrlParts(canvas.toDataURL("image/jpeg", quality));
  }
  return out;
}

async function postUpload(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: requestHeaders(),
    body: JSON.stringify(payload),
  });

  if (res.status === 401) {
    const err = new Error("Kunci akses ditolak.");
    err.status = 401;
    throw err;
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    throw new Error(
      (data && (data.detail || data.message)) || "Server membalas " + res.status
    );
  }
  return (data && data.text) || "";
}

function lockOut() {
  accessKey = "";
  saveAccessKey("");
  showGate("Kunci akses ditolak. Coba masukkan lagi.");
  setStatus("terkunci", "error");
}

function insertIntoComposer(text) {
  const value = String(text || "").trim();
  if (!value) return;

  const existing = els.input.value.trim();
  els.input.value = existing ? existing + " " + value : value;
  autoGrow();
  els.input.focus();
}

async function withUpload(label, task) {
  setBusy(true);
  setStatus(label, "searching");
  els.attachNote.textContent = label + "…";

  try {
    insertIntoComposer(await task());
    setStatus("siap", "idle");
  } catch (err) {
    if (err && err.status === 401) {
      lockOut();
      return;
    }
    toast(err.message || "Berkas gagal diproses.");
    setStatus("gagal", "error");
  } finally {
    els.attachNote.textContent = "";
    setBusy(false);
  }
}

async function handleImageFile(file) {
  if (!file) return;

  await withUpload("membaca gambar", async () => {
    const parts = await downscaleImage(file);
    return postUpload("/api/vision", {
      mime: parts.mime,
      data: parts.base64,
      filename: file.name || "",
    });
  });
}

async function handleAudioFile(file) {
  if (!file) return;

  if (!sttReady) {
    toast("Speech to text belum dikonfigurasi di server. Isi STT_BASE_URL dan STT_API_KEY.");
    return;
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    toast("Berkas audio lebih dari 3 MB. Potong dulu atau rekam lebih singkat.");
    return;
  }

  await withUpload("menyalin suara", async () => {
    const raw = await readFileAsDataURL(file);
    const parts = dataUrlParts(raw);
    return postUpload("/api/transcribe", {
      mime: file.type || parts.mime,
      data: parts.base64,
      filename: file.name || "",
    });
  });
}

/* ---------------- pencarian suara langsung ---------------- */

const LIVE_MAX_MS = 60000;
const LIVE_SILENCE_MS = 1600;
const LIVE_RMS_THRESHOLD = 0.02;
const LIVE_MIN_BYTES = 2000;

let live = null;

function pickRecorderMime() {
  const pilihan = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  if (!window.MediaRecorder) return "";
  for (const type of pilihan) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return "";
}

async function startLive() {
  if (!sttReady) {
    toast("Speech to text belum dikonfigurasi di server. Isi STT_BASE_URL dan STT_API_KEY.");
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
    toast("Browser ini tidak mendukung perekaman suara.");
    return;
  }

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    const nama = err && err.name;
    if (nama === "NotAllowedError" || nama === "SecurityError") {
      toast("Akses mikrofon ditolak. Izinkan lewat ikon di address bar, lalu coba lagi.");
    } else if (nama === "NotFoundError") {
      toast("Tidak ada mikrofon yang terdeteksi.");
    } else {
      toast("Mikrofon tidak bisa dibuka.");
    }
    return;
  }

  const mime = pickRecorderMime();
  live = {
    active: true,
    cancelled: false,
    stream,
    mime,
    chunks: [],
    startedAt: Date.now(),
    spoken: false,
    silenceStart: 0,
    ctx: null,
    analyser: null,
    raf: 0,
    timer: 0,
  };

  try {
    live.recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  } catch {
    stream.getTracks().forEach((track) => track.stop());
    toast("Perekaman suara gagal dimulai.");
    return;
  }

  live.recorder.ondataavailable = (event) => {
    if (event.data && event.data.size) live.chunks.push(event.data);
  };
  live.recorder.onstop = () => {
    finishLive();
  };

  live.recorder.start();

  recording = true;
  syncComposer();
  els.pickLive.textContent = "Berhenti";
  els.pickLive.setAttribute("aria-pressed", "true");
  els.level.hidden = false;
  setStatus("mendengarkan", "searching");

  live.timer = setInterval(() => {
    if (!live || !live.active) return;
    const detik = Math.floor((Date.now() - live.startedAt) / 1000);
    els.attachNote.textContent = "mendengarkan " + detik + "s";
    if (Date.now() - live.startedAt > LIVE_MAX_MS) stopLive(false);
  }, 200);

  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    live.ctx = new Ctx();
    const source = live.ctx.createMediaStreamSource(stream);
    live.analyser = live.ctx.createAnalyser();
    live.analyser.fftSize = 512;
    source.connect(live.analyser);
    monitorLive();
  } catch {
    /* tanpa analiser rekaman tetap jalan; hanya level dan auto-berhenti yang mati */
  }
}

function monitorLive() {
  if (!live || !live.active || !live.analyser) return;

  const buffer = new Uint8Array(live.analyser.fftSize);
  live.analyser.getByteTimeDomainData(buffer);

  let jumlah = 0;
  for (let i = 0; i < buffer.length; i += 1) {
    const nilai = (buffer[i] - 128) / 128;
    jumlah += nilai * nilai;
  }
  const rms = Math.sqrt(jumlah / buffer.length);

  const bar = els.level.firstElementChild;
  if (bar) bar.style.width = Math.min(100, Math.round(rms * 400)) + "%";

  const sekarang = Date.now();
  if (rms > LIVE_RMS_THRESHOLD) {
    live.spoken = true;
    live.silenceStart = 0;
  } else if (live.spoken) {
    if (!live.silenceStart) {
      live.silenceStart = sekarang;
    } else if (sekarang - live.silenceStart > LIVE_SILENCE_MS) {
      stopLive(false);
      return;
    }
  }

  live.raf = requestAnimationFrame(monitorLive);
}

function stopLive(cancel) {
  if (!live || !live.active) return;

  live.active = false;
  live.cancelled = Boolean(cancel);
  recording = false;

  clearInterval(live.timer);
  cancelAnimationFrame(live.raf);

  try {
    if (live.recorder && live.recorder.state !== "inactive") live.recorder.stop();
  } catch {
    /* diabaikan */
  }
  try {
    live.stream.getTracks().forEach((track) => track.stop());
  } catch {
    /* diabaikan */
  }
  try {
    if (live.ctx) live.ctx.close();
  } catch {
    /* diabaikan */
  }
  live.analyser = null;

  els.pickLive.textContent = "Bicara";
  els.pickLive.setAttribute("aria-pressed", "false");
  els.level.hidden = true;
  const bar = els.level.firstElementChild;
  if (bar) bar.style.width = "0%";
  syncComposer();
}

async function finishLive() {
  const rekaman = live;
  if (!rekaman) return;

  const blob = new Blob(rekaman.chunks, { type: rekaman.mime || "audio/webm" });
  const dibatalkan = rekaman.cancelled;
  const terlaluPendek = blob.size < LIVE_MIN_BYTES;
  rekaman.chunks = [];

  els.attachNote.textContent = "";

  if (dibatalkan || terlaluPendek) {
    setStatus("siap", "idle");
    return;
  }

  setBusy(true);
  setStatus("menyalin suara", "searching");

  try {
    const raw = await readFileAsDataURL(blob);
    const parts = dataUrlParts(raw);
    const teks = String(
      await postUpload("/api/transcribe", {
        mime: blob.type || parts.mime,
        data: parts.base64,
        filename: "bicara.webm",
      }) || ""
    ).trim();

    if (!teks) {
      toast("Tidak ada suara yang terdengar. Coba bicara lebih dekat ke mikrofon.");
      setStatus("siap", "idle");
      return;
    }

    els.input.value = teks;
    autoGrow();
    setStatus("siap", "idle");
    setBusy(false);
    els.composer.requestSubmit();
  } catch (err) {
    if (err && err.status === 401) {
      lockOut();
      return;
    }
    toast(err.message || "Suara gagal ditranskripsi.");
    setStatus("gagal", "error");
  } finally {
    setBusy(false);
  }
}

let toastTimer;
function toast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    els.toast.hidden = true;
  }, 7000);
}

function scrollToEnd(force) {
  const nearBottom =
    window.innerHeight + window.scrollY >= document.body.scrollHeight - 240;
  if (force || nearBottom) {
    window.scrollTo(0, document.body.scrollHeight);
  }
}

/* ---------------- render ---------------- */

function createTurnElement(turn) {
  const wrap = el("div", "turn turn--" + (turn.role === "user" ? "user" : "bot"));
  if (turn.error) wrap.classList.add("turn--error");

  if (turn.role === "user") {
    wrap.append(el("p", "query", turn.content));
  } else {
    wrap.append(el("p", "answer", turn.content || ""));
  }

  return wrap;
}

function renderAll() {
  turns.forEach((turn) => els.thread.append(createTurnElement(turn)));
  els.intro.hidden = turns.length > 0;
}

/* ---------------- streaming ---------------- */

function parseFrame(frame) {
  let event = "message";
  const dataLines = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }

  if (!dataLines.length) return null;

  const raw = dataLines.join("\n");
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    data = { text: raw };
  }
  return { event, data };
}

async function streamChat({ message, history, days, onEvent }) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: requestHeaders(),
    body: JSON.stringify({ message, history, days }),
  });

  if (res.status === 401) {
    const err = new Error("Kunci akses ditolak. Masukkan kunci yang benar.");
    err.status = 401;
    throw err;
  }

  if (!res.ok || !res.body) {
    throw new Error("Server membalas dengan status " + res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let cut;
      while ((cut = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const parsed = parseFrame(frame);
        if (parsed) onEvent(parsed);
      }
    }

    if (buffer.trim()) {
      const parsed = parseFrame(buffer);
      if (parsed) onEvent(parsed);
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

/* ---------------- alur tanya jawab ---------------- */

async function ask(raw) {
  const message = String(raw || "").trim();
  if (!message || busy) return;

  const prior = turns
    .filter((t) => t.content.trim())
    .slice(-HISTORY_SENT_TURNS)
    .map((t) => ({ role: t.role, content: t.content }));

  els.intro.hidden = true;

  const userTurn = { role: "user", content: message };
  turns.push(userTurn);
  els.thread.append(createTurnElement(userTurn));
  saveTurns();

  const botTurn = { role: "assistant", content: "" };
  const botEl = createTurnElement(botTurn);
  const answerEl = botEl.querySelector(".answer");
  answerEl.classList.add("cursor");
  els.thread.append(botEl);

  setBusy(true);
  setStatus("menelusuri", "searching");
  scrollToEnd(true);

  try {
    await streamChat({
      message,
      history: prior,
      days: els.recent.checked ? 7 : null,
      onEvent: ({ event, data }) => {
        if (event === "token") {
          if (!botTurn.content) setStatus("menjawab", "answering");
          botTurn.content += data.text || "";
          answerEl.textContent = botTurn.content;
          scrollToEnd(false);
        } else if (event === "final") {
          botTurn.content = data.text || botTurn.content;
          answerEl.textContent = botTurn.content;
          scrollToEnd(false);
        } else if (event === "error") {
          throw new Error(data.message || "kesalahan tidak dikenal");
        }
      },
    });

    answerEl.classList.remove("cursor");
    setStatus("siap", "idle");
  } catch (err) {
    answerEl.classList.remove("cursor");

    if (err && err.status === 401) {
      botTurn.dropped = true;
      botEl.remove();
      turns = turns.filter((turn) => turn !== userTurn);
      accessKey = "";
      saveAccessKey("");
      showGate("Kunci akses ditolak. Coba masukkan lagi.");
      setStatus("terkunci", "error");
      return;
    }

    botEl.classList.add("turn--error");
    botTurn.error = true;
    botTurn.content = err.message || "Gagal menghubungi server.";
    answerEl.textContent = botTurn.content;
    setStatus("gagal", "error");
  } finally {
    setBusy(false);
    if (!botTurn.dropped) {
      turns.push(botTurn);
      saveTurns();
    }
    scrollToEnd(false);
    if (!gateOpen) els.input.focus();
  }
}

/* ---------------- kesehatan server ---------------- */

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();

    if (!data.deepseek_key || !data.tavily_key) {
      const missing = [
        !data.deepseek_key && "DEEPSEEK_API_KEY",
        !data.tavily_key && "TAVILY_API_KEY",
      ]
        .filter(Boolean)
        .join(" dan ");
      toast("Belum ada " + missing + " di file .env. Isi dulu, lalu restart server.");
      setStatus("tanpa kunci", "error");
    }

    sttReady = data.stt_ready === true;

    if (data.access_required && !accessKey) {
      showGate();
    }
  } catch {
    toast("Server tidak merespons. Pastikan uvicorn sedang berjalan di port 8000.");
    setStatus("offline", "error");
  }
}

/* ---------------- pemasangan ---------------- */

function autoGrow() {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 192) + "px";
}

els.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = els.input.value;
  els.input.value = "";
  autoGrow();
  ask(text);
});

els.input.addEventListener("input", autoGrow);

els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    els.composer.requestSubmit();
  }
});

els.clear.addEventListener("click", () => {
  if (!turns.length) return;
  if (!confirm("Hapus seluruh riwayat percakapan?")) return;
  turns = [];
  saveTurns();
  [...els.thread.querySelectorAll(".turn")].forEach((node) => node.remove());
  els.intro.hidden = false;
  setStatus("siap", "idle");
});

document.querySelectorAll(".example").forEach((button) => {
  button.addEventListener("click", () => ask(button.textContent.trim()));
});

els.gateForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = els.gateInput.value.trim();
  if (!value) return;

  accessKey = value;
  saveAccessKey(value);
  els.gateInput.value = "";
  hideGate();
  setStatus("siap", "idle");
  toast("Kunci akses tersimpan di browser ini.");
});

els.pickImage.addEventListener("click", () => els.fileImage.click());
els.pickAudio.addEventListener("click", () => els.fileAudio.click());

els.pickLive.addEventListener("click", () => {
  if (recording) stopLive(false);
  else startLive();
});

els.fileImage.addEventListener("change", (event) => {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  handleImageFile(file);
});

els.fileAudio.addEventListener("change", (event) => {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  handleAudioFile(file);
});

renderAll();
checkHealth();
els.input.focus();
