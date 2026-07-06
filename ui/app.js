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

function addTurn(text) {
  const was = atBottom();
  const wrap = document.createElement("div");
  wrap.className = "turn";
  const hand = document.createElement("span");
  hand.className = "turn__hand";
  hand.textContent = "you";
  const p = document.createElement("p");
  p.textContent = text;
  wrap.append(hand, p);
  flow.appendChild(wrap);
  lastKind = "turn";
  autoscroll(was);
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
 * Drawers
 * --------------------------------------------------------------------- */
const drawerData = { sheet: null, canon: null, map: null };
const drawerFresh = { sheet: false, canon: false, map: false };

function setDrawer(which, markdown) {
  drawerData[which] = markdown;
  const el = $(`#drawer-${which}`);
  if (which === "map" && !markdown) {
    el.className = "slot map-slot";
    el.textContent = "no map shipped";
  } else {
    el.className = "md";
    el.innerHTML = markdown ? renderMarkdown(markdown)
      : `<p><em>Nothing shipped in <span class="u-mono">${which === "canon" ? "surface.md" : which + ".md"}</span> yet.</em></p>`;
  }
  // freshness pip on the rail tab, cleared when opened
  const open = pullout.getAttribute("data-open") === "true" && pullout.getAttribute("data-active") === which;
  if (!open) {
    drawerFresh[which] = true;
    const tab = $(`.rail__tab[data-pull="${which}"]`);
    if (tab) tab.setAttribute("data-live", "true");
  }
}

/* --------------------------------------------------------------------- *
 * Resume ribbon / notary / meta / session
 * --------------------------------------------------------------------- */
let resumeDismissed = false;

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
  });
  es.addEventListener("meta", (e) => {
    const d = JSON.parse(e.data);
    if (d.story) { $("#story-title").textContent = d.story; document.title = d.story + " — Baton"; }
  });
  es.addEventListener("story", (e) => {
    const d = JSON.parse(e.data);
    if (d.kind === "prose") addProse(d.text);
    else if (d.kind === "turn") addTurn(d.text);
  });
  es.addEventListener("roll", (e) => addRoll(JSON.parse(e.data)));
  es.addEventListener("drawer", (e) => {
    const d = JSON.parse(e.data);
    setDrawer(d.which, d.markdown);
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
      hint.textContent = "Delivered to the table — the narrator will pick it up.";
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
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 144) + "px";
});

/* --------------------------------------------------------------------- *
 * Pull-out panels (rail + mobile), cast sheet, mode toggle — chrome
 * --------------------------------------------------------------------- */
const pullout = $("#pullout");
const DOC_FILES = { sheet: "sheet.md", canon: "surface.md", map: "map.md" };
const DOC_TITLES = { sheet: "Sheet", canon: "Canon", map: "Map" };

function openPull(doc) {
  pullout.setAttribute("data-active", doc);
  pullout.setAttribute("data-open", "true");
  $("#pull-title").textContent = DOC_TITLES[doc];
  $("#pull-file").textContent = DOC_FILES[doc];
  $$(".rail__tab").forEach((t) => t.classList.toggle("is-active", t.dataset.pull === doc));
  // clear freshness
  drawerFresh[doc] = false;
  const tab = $(`.rail__tab[data-pull="${doc}"]`);
  if (tab) tab.setAttribute("data-live", "false");
}
function closePull() {
  pullout.setAttribute("data-open", "false");
  $$(".rail__tab").forEach((t) => t.classList.remove("is-active"));
}
function togglePull(doc) {
  const open = pullout.getAttribute("data-open") === "true";
  const active = pullout.getAttribute("data-active");
  if (open && active === doc) closePull(); else openPull(doc);
}
$$("[data-pull]").forEach((b) => b.addEventListener("click", () => togglePull(b.dataset.pull)));
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

let mode = "light";
$("#mode-toggle").addEventListener("click", () => {
  mode = mode === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-mode", mode);
  $("#mode-toggle").textContent = mode === "dark" ? "☀" : "☾";
});

/* keep the pull-out anchored below the actual top bar height */
function syncTopbarH() {
  document.documentElement.style.setProperty("--topbar-h", $(".topbar").offsetHeight + "px");
}
window.addEventListener("resize", syncTopbarH);

/* ------------------------------- boot ------------------------------- */
syncTopbarH();
setSession("connecting");
connect();
