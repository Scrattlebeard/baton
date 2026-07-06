/* =====================================================================
   Baton UI — live driver
   Consumes the observer backend (server.py) over Server-Sent Events and
   paints the fixed markup. Player turns POST to /input, which the server
   drops in the inbox; a driver (see drivers/) turns that into model input.
   The markup NEVER changes between skins — a story's ui/theme.css only
   overrides tokens. This file is genre-agnostic.
   ===================================================================== */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* --------------------------------------------------------------------- *
 * Minimal, dependency-free markdown → HTML for the drawer panels.
 * Deliberately small: headings, bold, italic, code, lists, hr, and the
 * ledger-style 'Label: value' rows. Text is escaped first; no raw HTML.
 * --------------------------------------------------------------------- */
function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, '<span class="u-mono">$1</span>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
    .replace(/\b_([^_]+)_\b/g, "<em>$1</em>");
}
function renderMarkdown(md) {
  if (!md) return "";
  const lines = md.replace(/\r/g, "").split("\n");
  const out = [];
  let list = null, para = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (let raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { flushPara(); flushList(); continue; }
    let m;
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      flushPara(); flushList();
      const lvl = Math.min(m[1].length + 2, 6);
      out.push(`<h${lvl}>${inline(m[2])}</h${lvl}>`);
    } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      flushPara(); flushList(); out.push("<hr>");
    } else if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
      flushPara(); if (list !== "ul") { flushList(); out.push("<ul>"); list = "ul"; }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      flushPara(); if (list !== "ol") { flushList(); out.push("<ol>"); list = "ol"; }
      out.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^([A-Za-z][\w ()/'-]{0,28}):\s+(.+)$/)) && !line.includes("://")) {
      // 'Vigor: ●●●○○' → a stat row (sheet ledgers)
      flushPara(); flushList();
      out.push(`<div class="stat-row"><span>${esc(m[1])}</span><span>${inline(m[2])}</span></div>`);
    } else {
      flushList(); para.push(line.trim());
    }
  }
  flushPara(); flushList();
  return out.join("\n");
}

/* --------------------------------------------------------------------- *
 * Stream flow — prose / turn / roll, appended in arrival order.
 * --------------------------------------------------------------------- */
const flow = $("#stream-flow");
const stream = $("#stream");

function atBottom() {
  return stream.scrollHeight - stream.scrollTop - stream.clientHeight < 120;
}
function autoscroll(was) { if (was) stream.scrollTop = stream.scrollHeight; }

let lastKind = null;

function addProse(text) {
  const was = atBottom();
  const div = document.createElement("div");
  div.className = "prose";
  // split into paragraphs on blank lines
  text.split(/\n{2,}/).forEach((chunk) => {
    const p = document.createElement("p");
    p.innerHTML = inline(chunk.replace(/\n/g, " "));
    div.appendChild(p);
  });
  flow.appendChild(div);
  lastKind = "prose";
  autoscroll(was);
}

function addTurn(text, pending = false) {
  const was = atBottom();
  const wrap = document.createElement("div");
  wrap.className = "turn";
  if (pending) wrap.dataset.pending = "true";   // faded until the transcript confirms it
  const hand = document.createElement("span");
  hand.className = "turn__hand";
  hand.textContent = "you";
  const p = document.createElement("p");
  p.textContent = text;
  wrap.append(hand, p);
  flow.appendChild(wrap);
  lastKind = "turn";
  autoscroll(was);
  return wrap;
}

/* "the narrator is writing" — shown from Send until the response lands, so a
 * slow model never leaves the screen looking dead. Client-side: it reflects
 * THIS browser's send. */
let working = false;
let workingTimer = null;
let currentActivity = "";        // the redacted verb-phrase, from activity events
const pendingTurns = [];         // {text, el} awaiting transcript confirmation

function activityPhrase(verb, target) {
  if (target) return `${verb} ${target}`;
  return {
    reasoning: "reasoning",
    writing: "writing a file",
    consulting: "consulting the material",
    "rolling dice": "rolling the dice",
    "saving progress": "saving progress",
    "running a command": "running a command",
    searching: "searching",
    "reading a source": "reading a source",
    "using a tool": "working",
  }[verb] || verb;
}

function renderWorkingLabel() {
  const lbl = document.querySelector("#working-indicator .working__label");
  if (lbl) lbl.textContent = "the narrator is " + (currentActivity || "writing");
}

function showWorking() {
  hint.textContent = "The narrator is writing…";
  if (!working) {
    working = true;
    const el = document.createElement("div");
    el.className = "working";
    el.id = "working-indicator";
    el.innerHTML = `<span class="working__label"></span>` +
      `<span class="working__dots"><i></i><i></i><i></i></span>`;
    flow.appendChild(el);
    stream.scrollTop = stream.scrollHeight;
    workingTimer = setTimeout(() => {
      const lbl = document.querySelector("#working-indicator .working__label");
      if (lbl) lbl.textContent = "still working — a slower model can take a while";
    }, 25000);
  }
  renderWorkingLabel();
}

function setActivity(verb, target) {
  currentActivity = activityPhrase(verb, target);
  showWorking();          // an activity implies the model is working; show + relabel
}

function clearWorking() {
  working = false;
  currentActivity = "";
  if (workingTimer) { clearTimeout(workingTimer); workingTimer = null; }
  const el = $("#working-indicator");
  if (el) el.remove();
  hint.textContent = "Write freely. Enter sends, Shift+Enter for a new line.";
  // the turn finished, so any still-pending echoes have landed — un-fade them
  // (they stay in pendingTurns so an exact-match turn event is still deduped)
  pendingTurns.forEach((p) => p.el.removeAttribute("data-pending"));
}

function addRoll(r) {
  const was = atBottom();
  const box = document.createElement("div");
  box.className = "roll";
  const dice = (r.dice || []).map((n) => `<span class="die">${n}</span>`).join("");
  box.innerHTML =
    `<span class="roll__label">${esc(r.label || "roll")}</span>` +
    `<span class="roll__dice">${dice}</span>` +
    `<span class="roll__op">${r.mod ? (r.mod > 0 ? "+ " + r.mod : "− " + Math.abs(r.mod)) : ""}</span>` +
    `<span class="roll__op">=</span>` +
    `<span class="roll__total">${r.total}</span>` +
    `<span class="roll__note">${esc(r.note || "")}</span>`;
  flow.appendChild(box);
  lastKind = "roll";
  autoscroll(was);
}

/* --------------------------------------------------------------------- *
 * Drawers — built at runtime, one per drawer the server announces. A drawer
 * exists iff its backing file does; the DOM holds exactly the live set, so
 * there is nothing to hide (open-ended: any ui/drawers/*.md shows up here).
 * --------------------------------------------------------------------- */
const railEl = $("#rail");
const mobileDrawersEl = $("#mobile-drawers");
const pulloutBody = $("#pullout-body");
const railTpl = $("#tpl-rail-tab");
const mobileTpl = $("#tpl-mobile-drawer");
const paneTpl = $("#tpl-drawer-pane");

// key -> { title, file, tab, mobile, pane }
const drawers = new Map();

function firstLetter(title) {
  const c = (title || "?").trim()[0];
  return c ? c.toUpperCase() : "?";
}

function upsertDrawer(key, title, file, markdown) {
  if (markdown === null || markdown === undefined) { removeDrawer(key); return; }
  let d = drawers.get(key);
  if (!d) {
    const tab = railTpl.content.firstElementChild.cloneNode(true);
    tab.dataset.pull = key;
    const mobile = mobileTpl.content.firstElementChild.cloneNode(true);
    mobile.dataset.pull = key;
    const pane = paneTpl.content.firstElementChild.cloneNode(true);
    pane.dataset.doc = key;
    railEl.appendChild(tab);
    mobileDrawersEl.appendChild(mobile);
    pulloutBody.appendChild(pane);
    d = { tab, mobile, pane };
    drawers.set(key, d);
  }
  d.title = title; d.file = file;
  d.tab.querySelector(".rail__letter").textContent = firstLetter(title);
  d.tab.querySelector(".rail__name").textContent = title;
  d.tab.title = `${title} · ${file}`;
  d.mobile.querySelector(".mobile-bar__label").textContent = title;
  d.pane.querySelector(".md").innerHTML = markdown ? renderMarkdown(markdown) : `<p><em>(empty)</em></p>`;
  // freshness pip unless this drawer is the one currently open
  const open = pullout.getAttribute("data-open") === "true" && pullout.getAttribute("data-active") === key;
  if (!open) d.tab.setAttribute("data-live", "true");
}

function removeDrawer(key) {
  const d = drawers.get(key);
  if (!d) return;
  d.tab.remove(); d.mobile.remove(); d.pane.remove();
  drawers.delete(key);
  if (pullout.getAttribute("data-active") === key && pullout.getAttribute("data-open") === "true") closePull();
}

function clearDrawers() {
  for (const key of [...drawers.keys()]) removeDrawer(key);
}

/* --------------------------------------------------------------------- *
 * Resume ribbon / notary / meta / session
 * --------------------------------------------------------------------- */
let resumeDismissed = false;
let foundingDismissed = false;

function setResume(r) {
  if (resumeDismissed || !r || !r.where) { $("#resume").hidden = true; return; }
  $("#resume-where").textContent = r.where;
  if (r.next) { $("#resume-next").textContent = r.next; $("#resume-next-line").hidden = false; }
  else { $("#resume-next-line").hidden = true; }
  $("#resume").hidden = false;
}

function setNotary(n) {
  if (!n) { $("#notary").hidden = true; return; }
  $("#notary-text").textContent = n.text || "hidden state logged";
  $("#notary-seal").textContent = n.seal || "—";
  $("#notary-time").textContent = n.time || "";
  $("#notary").hidden = false;
}

function setSession(state, detail) {
  const labels = {
    connecting: "connecting…",
    watching: "watching for changes",
    error: "narrator unreachable — retrying",
  };
  $("#session").setAttribute("data-state", state);
  $("#session-label").textContent = detail ? `${labels[state]}` : (labels[state] || state);
}

/* --------------------------------------------------------------------- *
 * SSE wiring
 * --------------------------------------------------------------------- */
function connect() {
  const es = new EventSource("/events");

  es.addEventListener("reset", () => {
    flow.innerHTML = "";
    lastKind = null;
    clearDrawers();  // fresh snapshot rebuilds only the present drawers
    if (!foundingDismissed) $("#founding").hidden = true;
  });
  es.addEventListener("founding", (e) => {
    if (foundingDismissed) return;
    const d = JSON.parse(e.data);
    $("#founding-where").textContent =
      `${d.name || "This story"} has been scaffolded from the skeleton. Nothing is written yet — build it together.`;
    $("#founding").hidden = false;
  });
  es.addEventListener("meta", (e) => {
    const d = JSON.parse(e.data);
    if (d.story) { $("#story-title").textContent = d.story; document.title = d.story + " — Baton"; }
  });
  es.addEventListener("story", (e) => {
    const d = JSON.parse(e.data);
    if (d.kind === "prose") addProse(d.text);
    else if (d.kind === "turn") {
      // if this turn matches one we optimistically echoed, just confirm it
      const i = pendingTurns.findIndex((p) => p.text === d.text.trim());
      if (i !== -1) { pendingTurns[i].el.removeAttribute("data-pending"); pendingTurns.splice(i, 1); }
      else addTurn(d.text);
    }
  });
  es.addEventListener("roll", (e) => addRoll(JSON.parse(e.data)));
  es.addEventListener("drawer", (e) => {
    const d = JSON.parse(e.data);
    upsertDrawer(d.which, d.title, d.file, d.markdown);
  });
  // busy = a turn is in flight (inbox non-empty); reliable start/stop
  es.addEventListener("busy", (e) => {
    JSON.parse(e.data).active ? showWorking() : clearWorking();
  });
  // activity = redacted detail of what the model is doing right now
  es.addEventListener("activity", (e) => {
    const d = JSON.parse(e.data);
    setActivity(d.verb, d.target);
  });
  es.addEventListener("resume", (e) => setResume(JSON.parse(e.data)));
  es.addEventListener("notary", (e) => setNotary(JSON.parse(e.data)));
  es.addEventListener("session", (e) => {
    const d = JSON.parse(e.data);
    setSession(d.state, d.detail);
  });

  es.onopen = () => setSession("watching");
  es.onerror = () => setSession("error");
}

/* --------------------------------------------------------------------- *
 * Composer — POST the turn to /input (the server drops it in the inbox)
 * --------------------------------------------------------------------- */
const input = $("#composer-input");
const sendBtn = $("#composer-send");
const hint = $("#composer-hint");
let inputManual = false;   // true once the user drags the composer height

hint.textContent = "Write freely. Enter sends, Shift+Enter for a new line.";

async function send() {
  const text = input.value.trim();
  if (!text) return;
  sendBtn.disabled = true;
  try {
    const res = await fetch("/input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (res.ok) {
      input.value = "";
      input.style.height = "auto";
      const el = addTurn(text, true);        // show your turn at once (pending)
      pendingTurns.push({ text, el });
      showWorking();                          // "the narrator is writing…"
    } else {
      hint.textContent = "Couldn't deliver that turn. Try again.";
    }
  } catch {
    hint.textContent = "Backend unreachable. Is server.py running?";
  } finally {
    sendBtn.disabled = false;
  }
}

sendBtn.addEventListener("click", send);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
input.addEventListener("input", () => {
  if (inputManual) return;   // hand-sized: leave it be, scroll within
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 144) + "px";
});

/* --------------------------------------------------------------------- *
 * Pull-out panels (rail + mobile), cast sheet, mode toggle — chrome
 * --------------------------------------------------------------------- */
const pullout = $("#pullout");

function openPull(key) {
  const d = drawers.get(key);
  if (!d) return;
  pullout.setAttribute("data-active", key);
  pullout.setAttribute("data-open", "true");
  $("#pull-title").textContent = d.title;
  $("#pull-file").textContent = d.file;
  $$(".pullout__doc").forEach((p) => p.classList.toggle("is-active", p.dataset.doc === key));
  $$(".rail__tab").forEach((t) => t.classList.toggle("is-active", t.dataset.pull === key));
  d.tab.setAttribute("data-live", "false");   // clear freshness pip
}
function closePull() {
  pullout.setAttribute("data-open", "false");
  $$(".rail__tab").forEach((t) => t.classList.remove("is-active"));
}
function togglePull(key) {
  const open = pullout.getAttribute("data-open") === "true";
  const active = pullout.getAttribute("data-active");
  if (open && active === key) closePull(); else openPull(key);
}
// event delegation — tabs are created at runtime, so bind on the containers
[railEl, mobileDrawersEl].forEach((container) =>
  container.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-pull]");
    if (btn) togglePull(btn.dataset.pull);
  })
);
$("#pull-close").addEventListener("click", closePull);
$("#pullout-backdrop").addEventListener("click", closePull);

function openCast() { $(".app").setAttribute("data-sheet", "true"); }
function closeCast() { $(".app").setAttribute("data-sheet", "false"); }
$("[data-cast]").addEventListener("click", openCast);
$("#sheet-backdrop").addEventListener("click", closeCast);

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closePull(); closeCast(); }
});

$("#resume-dismiss").addEventListener("click", () => {
  resumeDismissed = true;
  $("#resume").hidden = true;
});
$("#founding-dismiss").addEventListener("click", () => {
  foundingDismissed = true;
  $("#founding").hidden = true;
});

let mode = "light";
$("#mode-toggle").addEventListener("click", () => {
  mode = mode === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-mode", mode);
  $("#mode-toggle").textContent = mode === "dark" ? "☀" : "☾";
});

// full-width reading toggle — drop / restore the line-length cap
const appEl = $(".app");
const widthBtn = $("#width-toggle");
function setWideReading(on) {
  appEl.classList.toggle("wide-reading", on);
  widthBtn.classList.toggle("is-on", on);
  widthBtn.title = on ? "Cap line length (bookish)" : "Full-width reading";
  localStorage.setItem("baton.wideReading", on ? "1" : "0");
}
widthBtn.addEventListener("click", () => setWideReading(!appEl.classList.contains("wide-reading")));
setWideReading(localStorage.getItem("baton.wideReading") === "1");

/* keep the pull-out anchored below the actual top bar height */
function syncTopbarH() {
  document.documentElement.style.setProperty("--topbar-h", $(".topbar").offsetHeight + "px");
}
window.addEventListener("resize", syncTopbarH);

/* --------------------------------------------------------------------- *
 * Resizable boundaries — cast panel width, composer height. Drag with a
 * pointer; the size persists in localStorage. Pure layout, no backend.
 * --------------------------------------------------------------------- */
const REM = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;

function onDrag(handle, move) {
  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    handle.classList.add("dragging");
    appEl.classList.add("resizing");
    const onMove = (ev) => move(ev);
    const onUp = (ev) => {
      handle.releasePointerCapture(e.pointerId);
      handle.classList.remove("dragging");
      appEl.classList.remove("resizing");
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
  });
}

// cast panel: drag its left edge. Width = distance from the right edge.
const clampW = (w) => Math.max(15 * REM, Math.min(w, Math.min(46 * REM, window.innerWidth - 22 * REM)));
onDrag($("#rz-sidebar"), (ev) => {
  const w = clampW(window.innerWidth - ev.clientX);
  document.documentElement.style.setProperty("--sidebar-w", w + "px");
  localStorage.setItem("baton.sidebarW", String(w));
});

// composer: drag its top edge upward to grow the input, downward to shrink.
const clampH = (h) => Math.max(1.5 * REM, Math.min(h, window.innerHeight * 0.6));
onDrag($("#rz-composer"), (ev) => {
  const rect = input.getBoundingClientRect();
  const h = clampH(rect.bottom - ev.clientY);
  inputManual = true;
  input.style.height = h + "px";
  input.style.maxHeight = h + "px";
  localStorage.setItem("baton.inputH", String(h));
});

// restore persisted sizes
(function restoreSizes() {
  const w = parseFloat(localStorage.getItem("baton.sidebarW"));
  if (w) document.documentElement.style.setProperty("--sidebar-w", clampW(w) + "px");
  const h = parseFloat(localStorage.getItem("baton.inputH"));
  if (h) {
    inputManual = true;
    const hh = clampH(h);
    input.style.height = hh + "px";
    input.style.maxHeight = hh + "px";
  }
})();

/* ------------------------------- boot ------------------------------- */
syncTopbarH();
setSession("connecting");   // drawers appear as the server announces them
connect();
