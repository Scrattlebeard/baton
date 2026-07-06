/* =====================================================================
   Baton UI — demo driver (static showcase, no backend)
   The MARKUP never changes between skins. This only swaps tokens
   (via [data-theme]) and per-genre text content into the fixed DOM,
   to prove the reskin-from-tokens claim with real, distinct stories.
   ===================================================================== */

const CONTENT = {
  default: {
    story: "Untitled Story",
    fixedMode: null,               // default theme respects the light/dark toggle
    resume: {
      where: "You're three chapters in. Last you set the story down, the letter was still on the table, unopened.",
      next: "It's your move.",
    },
    heading: "Chapter Three",
    proseA: [
      "The house was quiet in the particular way of houses that have just been left. A cup, still warm to the back of your hand. A door that had not quite finished closing, moving a finger's width in the draught and then stopping, as if it had thought better of it.",
      "Whatever had happened here had happened without hurry, and that was the part that unsettled you most.",
    ],
    proseB: [
      "The letter lay where you remembered it, square to the edge of the table, your own name on the front in a hand you did not know.",
    ],
    turn: "I pick up the cup — more to have something in my hands than for any reason I could name — and I wait.",
    roll: { label: "Notice", dice: [3], mod: 1, total: 4, note: "a quiet check, resolved in the open" },
    proseC: [
      "From the next room, so soft you might have imagined it, someone begins to hum a tune you are almost certain you",
    ],
    notary: { text: "hidden roll logged", seal: "a3f9c12", time: "just now" },
    cast: {
      empty: "No cast has been introduced yet. Portraits arrive later; the card shape is reserved.",
      members: [{ name: "?", desc: "Someone is humming in the next room." }],
    },
    sheet: `<p><strong>You</strong></p><p><em>This story hasn't shipped a character sheet.</em> A story can supply one in <span class="u-mono">sheet.md</span> and it renders here, live.</p>`,
    canon: `<p>Facts the story has committed to appear here, drawn from <span class="u-mono">surface.md</span>. Nothing sealed in <span class="u-mono">gm/</span> is ever served.</p>`,
    map: "no map shipped",
    illo: { cap: "the quiet house, just after", slot: "scene illustration", caption: "An empty room, a cup still warm. Illustration slots are author-optional; asset generation arrives later." },
  },

  greenmarch: {
    story: "Greenmarch — Book One",
    fixedMode: null,
    resume: {
      where: "You left the drovers' road at dusk, three days east of Wickelow, and came down to the ford at Elder-Wick in the rain.",
      next: "The miller is waiting for your answer.",
    },
    heading: "The Ford at Elder-Wick",
    proseA: [
      "Rain had been and gone, and the ford ran loud over its brown stones. On the far bank the mill stood with one window lit, and the wheel turned slow, complaining of the wet.",
      "A woman waited under the eave with her sleeves pushed back, watching you come. She did not wave.",
    ],
    proseB: [
      "“You'll be the one Tolliver sent,” she said, when you were close enough that she needn't raise her voice for it.",
    ],
    turn: "I set my staff against the doorframe and show her my open hands. “I'm the one nobody sent,” I tell her. “Which is worse, I know.”",
    roll: { label: "Persuasion", dice: [5], mod: 2, total: 7, note: "the miller weighs your candour" },
    proseC: [
      "She looks at you a long moment, and something in her jaw eases. “Well,” she says, “honesty's cheap and I'm poor, so you'd best come in before the",
    ],
    notary: { text: "hidden roll logged", seal: "a3f9c12", time: "14:22" },
    cast: {
      empty: "The road is quiet so far. Those you meet are kept here.",
      members: [{ name: "Maren Fell", desc: "Miller of Elder-Wick; keeps the old measures." }],
    },
    sheet: `<p><strong>Rowan</strong> &mdash; hedge-witch</p>
      <div class="stat-row"><span>Vigor</span><span class="pips">●●●○○</span></div>
      <div class="stat-row"><span>Wit</span><span class="pips">●●●●○</span></div>
      <div class="stat-row"><span>Guile</span><span class="pips">●●○○○</span></div>
      <p style="margin-top:.6rem"><em>Carrying:</em> ash staff, a twist of salt, one letter unopened.</p>`,
    canon: `<p>The drovers' road predates the crown. East of the Wick, tolls are paid in salt, never coin.</p><p><em>The miller's family has kept the ford for nine generations.</em></p>`,
    map: "Elder-Wick & the drovers' road",
    illo: { cap: "the ford at Elder-Wick", slot: "woodcut plate", caption: "The mill across the brown ford, one window lit — a woodcut-style plate." },
  },

  "neon-tithe": {
    story: "NEON TITHE // run_04",
    fixedMode: "dark",
    resume: {
      where: "Sub-level four, the Tithe office. Your credit's been flagged and the clock on the wall is counting down from ninety.",
      next: "Decide what you're willing to owe.",
    },
    heading: "Tithe Office // Sublevel 4",
    proseA: [
      "The rain up top never reaches here. It just becomes a sound, a pressure behind the ceiling tiles, a rumour of weather. The clerk is a face rendered in three colours of light and none of them are kind.",
      "“Your balance,” it says, and the number that hangs in the air between you is longer than your arm and mostly red.",
    ],
    proseB: [
      "Behind it, the ledger-wall scrolls without end — every debt in the district, indexed, breathing.",
    ],
    turn: "I don't look at the number. I look at the clerk. “I want to renegotiate the interest,” I say, and let my hand drift toward the deck at my hip.",
    roll: { label: "Intrusion", dice: [6, 2], mod: 1, total: 9, note: "you're inside its ledger before it finishes the sentence" },
    proseC: [
      "The lights stutter. For half a second the clerk's face is just a face — human, and afraid — and then the system catches itself and",
    ],
    notary: { text: "hidden roll logged", seal: "7c1e04b", time: "02:14" },
    cast: {
      empty: "No contacts logged for this run. Faces you clock are pinned here.",
      members: [{ name: "The Clerk", desc: "Tithe-office construct. Wears borrowed faces." }],
    },
    sheet: `<p><strong>VESH</strong> &mdash; runner</p>
      <div class="stat-row"><span>MEAT</span><span>4</span></div>
      <div class="stat-row"><span>WIRE</span><span>7</span></div>
      <div class="stat-row"><span>FACE</span><span>3</span></div>
      <div class="stat-row"><span>HEAT</span><span class="pips">▮▮▮▯▯▯</span></div>
      <p style="margin-top:.6rem"><em>Loadout:</em> breaker deck, one clean ID, a debt.</p>`,
    canon: `<p>The Tithe collects in years, not credits.</p><p><em>Nobody has read the whole contract and lived indexed.</em></p>`,
    map: "sublevel schematic — office ring",
    illo: { cap: "the tithe office", slot: "scene render", caption: "The clerk's three-colour face and the endless ledger-wall behind it." },
  },

  folio: {
    story: "FOLIO — The Drowned Stacks",
    fixedMode: "dark",
    resume: {
      where: "The Stacks, third gallery, waist-deep in still black water. Your lantern has maybe an hour of oil left in it.",
      next: "Choose which ledger to save from the water.",
    },
    heading: "The Third Gallery",
    proseA: [
      "The library did not fall so much as sink, patiently, over the better part of a century, and the water took the lower stacks the way ink takes a page.",
      "Here on the third gallery it laps at your ribs, black and very still. Somewhere ahead a page turns. There is no wind down here to turn it.",
    ],
    proseB: [
      "The drowned catalogue is still down here, they say, and still keeps its order — for anyone who remembers how to ask.",
    ],
    turn: "I lift the lantern and read the nearest spine aloud, testing whether the Stacks still answer to their own names.",
    roll: { label: "Lore (Cataloguing)", dice: [4, 4], mod: 3, total: 11, note: "the Stacks recognise a librarian's cadence" },
    proseC: [
      "The water shivers. Letters rise off a hundred sodden spines, hang trembling in the lanternlight, and begin — slowly, and then not slowly — to reshelve themselves around you, and one volume rises higher than the rest and",
    ],
    notary: { text: "hidden roll logged", seal: "e90b2af", time: "fathom 3" },
    cast: {
      empty: "Nothing down here has a face. What you infer is kept here.",
      members: [{ name: "The Subtext", desc: "Whatever reshelves the drowned Stacks. Never seen, only inferred." }],
    },
    sheet: `<p><strong>Quill</strong> &mdash; sub-librarian &middot; Lv 3</p>
      <div class="stat-row"><span>HP</span><span>18 / 24</span></div>
      <div class="stat-row"><span>Ink</span><span>6 / 6</span></div>
      <div class="stat-row"><span>Lore</span><span>11</span></div>
      <div class="stat-row"><span>Nerve</span><span>7</span></div>
      <div class="stat-row"><span>Salvage</span><span>5</span></div>
      <p style="margin-top:.6rem"><em>Ledger:</em> two dry codices, a bell, borrowed time.</p>`,
    canon: `<p>Every book saved from the water writes a line into you.</p><p><em>Every book lost writes one too.</em></p>`,
    map: "the Stacks — flooded galleries",
    illo: { cap: "the third gallery", slot: "scene plate", caption: "Lantern-light on black water; letters rising off the drowned spines." },
  },
};

/* --------------------------------------------------------------------- */
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

let currentSkin = "default";
let currentMode = "light";        // only meaningful for default
let narratorWriting = true;

function paras(el, arr, { cursorLast = false } = {}) {
  el.innerHTML = "";
  arr.forEach((t, i) => {
    const p = document.createElement("p");
    p.textContent = t;
    if (cursorLast && i === arr.length - 1) {
      const c = document.createElement("span");
      c.className = "cursor";
      p.appendChild(c);
    }
    el.appendChild(p);
  });
}

function renderRoll(roll) {
  const dice = $("#roll-dice");
  dice.innerHTML = "";
  roll.dice.forEach((n) => {
    const d = document.createElement("span");
    d.className = "die";
    d.textContent = n;
    dice.appendChild(d);
  });
  $("#roll-label").textContent = roll.label;
  $("#roll-mod").textContent = roll.mod ? "+ " + roll.mod : "";
  $("#roll-total").textContent = roll.total;
  $("#roll-note").textContent = roll.note;
}

function renderCast(cast) {
  $("#cast-empty").textContent = cast.empty;
  const list = $("#cast-list");
  list.innerHTML = "";
  cast.members.forEach((m) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML =
      `<div class="card__portrait slot">portrait</div>` +
      `<div class="card__body"><div class="card__name"></div><div class="card__desc"></div></div>`;
    card.querySelector(".card__name").textContent = m.name;
    card.querySelector(".card__desc").textContent = m.desc;
    list.appendChild(card);
  });
  const ghost = document.createElement("div");
  ghost.className = "card card--ghost";
  ghost.textContent = "a card appears as the story names someone";
  list.appendChild(ghost);
}

function applyContent(key) {
  const c = CONTENT[key];
  $("#story-title").textContent = c.story;
  $("#resume-where").textContent = c.resume.where;
  $("#resume-next").textContent = c.resume.next;
  $("#resume").hidden = false;
  $("#scene-heading").textContent = c.heading;
  paras($("#prose-a"), c.proseA);
  paras($("#prose-b"), c.proseB);
  paras($("#prose-c"), c.proseC, { cursorLast: narratorWriting });
  $("#turn-text").textContent = c.turn;
  renderRoll(c.roll);
  $("#notary-text").textContent = c.notary.text;
  $("#notary-seal").textContent = c.notary.seal;
  $("#notary-time").textContent = c.notary.time;
  renderCast(c.cast);
  $("#fig-cap").textContent = c.illo.cap;
  $("#fig-caption").textContent = c.illo.caption;
  $("#fig-slot").textContent = c.illo.slot;
  $("#drawer-sheet").innerHTML = c.sheet;
  $("#drawer-canon").innerHTML = c.canon;
  $("#drawer-map").textContent = c.map;
}

function applySkin(key) {
  currentSkin = key;
  const c = CONTENT[key];
  document.documentElement.setAttribute("data-theme", key);
  // story skins commit to a fixed mode; default follows the toggle
  const mode = c.fixedMode || currentMode;
  document.documentElement.setAttribute("data-mode", mode);
  $$(".skin__btn").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.skin === key))
  );
  const mt = $("#mode-toggle");
  mt.disabled = !!c.fixedMode;
  mt.textContent = (c.fixedMode || currentMode) === "dark" ? "☀" : "☾";
  applyContent(key);
}

function setNarratorWriting(on) {
  narratorWriting = on;
  $("#composer").setAttribute("data-disabled", String(on));
  $("#composer-input").disabled = on;
  $("#composer-hint").textContent = on
    ? "The narrator is writing… your turn opens when the passage settles."
    : "Write freely. Multiline; there's no wrong length. Enter sends, Shift+Enter for a new line.";
  // cursor lives on the last streaming paragraph
  const c = CONTENT[currentSkin];
  paras($("#prose-c"), c.proseC, { cursorLast: on });
  $$('[data-writing]').forEach((b) =>
    b.setAttribute("aria-pressed", String((b.dataset.writing === "true") === on))
  );
}

function setSession(state) {
  const labels = {
    connecting: "connecting…",
    watching: "watching for changes",
    error: "narrator unreachable — retrying",
  };
  $("#session").setAttribute("data-state", state);
  $("#session-label").textContent = labels[state];
  $$('[data-session]').forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.session === state))
  );
}

/* ------------------------------- wiring ------------------------------ */
$$(".skin__btn").forEach((b) =>
  b.addEventListener("click", () => applySkin(b.dataset.skin))
);

$("#mode-toggle").addEventListener("click", () => {
  currentMode = currentMode === "dark" ? "light" : "dark";
  if (currentSkin === "default") applySkin("default");
});

$("#resume-dismiss").addEventListener("click", () => ($("#resume").hidden = true));

/* ---- pull-out story-file panels (rail tabs + mobile bar) ---- */
const DOCS = {
  sheet: { title: "Sheet", file: "sheet.md", live: true },
  canon: { title: "Canon", file: "surface.md", live: false },
  map:   { title: "Map",   file: "map.md",    live: false },
};
const pullout = $("#pullout");

function openPull(doc) {
  const meta = DOCS[doc];
  pullout.setAttribute("data-active", doc);
  pullout.setAttribute("data-open", "true");
  pullout.setAttribute("data-live", String(meta.live));
  $("#pull-title").textContent = meta.title;
  $("#pull-file").textContent = meta.file;
  $$(".rail__tab").forEach((t) =>
    t.classList.toggle("is-active", t.dataset.pull === doc)
  );
}
function closePull() {
  pullout.setAttribute("data-open", "false");
  $$(".rail__tab").forEach((t) => t.classList.remove("is-active"));
}
function togglePull(doc) {
  const open = pullout.getAttribute("data-open") === "true";
  const active = pullout.getAttribute("data-active");
  if (open && active === doc) closePull();
  else openPull(doc);
}
$$("[data-pull]").forEach((b) =>
  b.addEventListener("click", () => togglePull(b.dataset.pull))
);
$("#pull-close").addEventListener("click", closePull);
$("#pullout-backdrop").addEventListener("click", closePull);

/* ---- inline scene illustration expand / collapse ---- */
$$("[data-figure]").forEach((btn) =>
  btn.addEventListener("click", () => {
    const f = btn.closest(".figure");
    f.setAttribute("data-open", f.getAttribute("data-open") === "true" ? "false" : "true");
  })
);

/* ---- cast bottom-sheet (mobile) ---- */
function openCast() { $(".app").setAttribute("data-sheet", "true"); }
function closeCast() { $(".app").setAttribute("data-sheet", "false"); }
$("[data-cast]").addEventListener("click", openCast);
$("#sheet-backdrop").addEventListener("click", closeCast);

// Esc closes whatever is open
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closePull(); closeCast(); }
});

$$('[data-writing]').forEach((b) =>
  b.addEventListener("click", () => setNarratorWriting(b.dataset.writing === "true"))
);
$$('[data-session]').forEach((b) =>
  b.addEventListener("click", () => setSession(b.dataset.session))
);

$("#demo-collapse").addEventListener("click", () => {
  const d = $("#demo");
  const c = d.getAttribute("data-collapsed") === "true";
  d.setAttribute("data-collapsed", String(!c));
  $("#demo-collapse").textContent = c ? "–" : "+";
});

/* keep the pull-out / backdrop anchored below the actual top bar height */
function syncTopbarH() {
  const h = $(".topbar").offsetHeight;
  document.documentElement.style.setProperty("--topbar-h", h + "px");
}
window.addEventListener("resize", syncTopbarH);

// auto-grow composer
const ta = $("#composer-input");
ta.addEventListener("input", () => {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 144) + "px";
});

/* ------------------------------- boot ------------------------------- */
syncTopbarH();
applySkin("default");
setNarratorWriting(true);
setSession("watching");
