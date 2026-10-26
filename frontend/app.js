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
};

let turns = loadTurns();
let accessKey = loadAccessKey();
let busy = false;
let gateOpen = false;

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

function setBusy(value) {
  busy = value;
  document.body.dataset.busy = value ? "true" : "false";
  els.send.disabled = value || gateOpen;
}

function showGate(message) {
  gateOpen = true;
  els.gate.hidden = false;
  els.send.disabled = true;
  if (message) toast(message);
  els.gateInput.focus();
}

function hideGate() {
  gateOpen = false;
  els.gate.hidden = true;
  els.send.disabled = busy;
  els.input.focus();
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

renderAll();
checkHealth();
els.input.focus();
