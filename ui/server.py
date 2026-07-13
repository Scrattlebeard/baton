#!/usr/bin/env python3
"""
Baton UI — observer backend.

A viewport with a membrane. It does exactly two things:

  1. READ PATH (spoiler-filtered) — watches a story directory and the
     Claude Code session transcript, and streams player-safe events to
     the browser over Server-Sent Events. gm/** and state.md are NEVER
     served; the transcript is filtered to assistant `text` and player
     turns only — tool calls, tool results, and thinking are dropped on
     the floor (that is where a `cat gm/world.md` payload would ride).

  2. INBOX WRITE — the composer POSTs a player turn; the server appends
     it to <story>/.baton/inbox/ and stops there. Turning that inbox
     into model input is a *driver's* job (see drivers/), deliberately
     decoupled: tmux, claude -p, the Agents SDK, or any client can
     consume the same inbox independently.

Stdlib only. No framework, no build step, no websocket library.

    python3 server.py /path/to/story [--port 8765] [--session UUID.jsonl]

Then open http://localhost:8765/ . A driver must be running for player
turns to advance the story; without one, turns queue in the inbox.
"""

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent
SKELETON = UI_DIR.parent / "templates" / "story-skeleton"

# ---------------------------------------------------------------------------
# The membrane. Only these basenames are ever served from the story dir.
# Everything else — gm/**, state.md, roll.py, .git, .baton — is invisible.
# ---------------------------------------------------------------------------
SERVED_FILES = {"surface.md", "sheet.md", "map.md", "rolls.log", "theme.css"}
# theme.css is looked up at <story>/ui/theme.css (a story's own skin).
# Plus: images under <story>/illustrations/ (rendered by the scriptorium's
# illustrator job) — player-safe BY CONSTRUCTION, because the doctrine
# requires briefs to derive from player-visible canon only. queue/
# (unrendered briefs), pending/ (renders awaiting the GM's image/facts
# reconciliation in gated stories), and the .md brief files are still never
# served: approved images only.
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg",
               ".jpeg": "image/jpeg", ".webp": "image/webp"}
UNSERVED_ILL = ("queue", "pending")

POLL_SECONDS = 0.5


# ===========================================================================
# Founding — scaffold an uninitialised directory into a Baton story
# ===========================================================================
def is_founded(story_dir: Path) -> bool:
    """A directory is already a story once it carries the core files."""
    return (story_dir / "state.md").exists() or (story_dir / "surface.md").exists()


def scaffold_story(story_dir: Path) -> bool:
    """Turn an empty/absent directory into a fresh Baton story: copy the
    skeleton, git init, and make the founding commit (the first precommitment
    the fairness doctrine rests on). Best-effort on git — a story without a
    repo still works, it just loses the timestamp proof until committed.
    Returns True on success."""
    if not SKELETON.is_dir():
        print(f"  ! no skeleton at {SKELETON}; cannot scaffold")
        return False
    story_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SKELETON, story_dir, dirs_exist_ok=True)
    try:
        if not (story_dir / ".git").exists():
            subprocess.run(["git", "-C", str(story_dir), "init", "-q"], check=True, timeout=10)
        subprocess.run(["git", "-C", str(story_dir), "add", "-A"], check=True, timeout=10)
        subprocess.run(["git", "-C", str(story_dir), "commit", "-q", "-m",
                        "Found story — scaffolded by Baton UI"], check=True, timeout=10)
    except Exception as e:
        print(f"  ! git founding commit skipped ({e}); scaffold is on disk, commit it manually")
    return True


# ===========================================================================
# Transcript: locate + filter
# ===========================================================================
def project_slug(story_dir: Path) -> str:
    """Claude Code stores transcripts under ~/.claude/projects/<slug>/,
    where <slug> is the absolute cwd with every non-alphanumeric run
    replaced by a dash. Verified against live dirs."""
    return re.sub(r"[^a-zA-Z0-9]", "-", str(story_dir.resolve()))


def read_session_pointer(story_dir: Path) -> Path | None:
    """A driver may pin its session by writing the transcript path to
    `<story>/.baton/session`. That pointer is authoritative over mtime
    guessing — it names the session the game is actually running in, even
    when older transcripts exist (a live story always has one)."""
    ptr = story_dir / ".baton" / "session"
    if not ptr.is_file():
        return None
    raw = ptr.read_text(errors="replace").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.exists() else None


def find_transcript(story_dir: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    pinned = read_session_pointer(story_dir)   # driver-pinned wins over mtime
    if pinned:
        return pinned
    proj = Path.home() / ".claude" / "projects" / project_slug(story_dir)
    if not proj.is_dir():
        return None
    jsonls = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonls[0] if jsonls else None


_MARKERS = ("<command-name>", "<local-command", "system-reminder",
            "<command-message>", "<command-args>")


def _is_noise(text: str) -> bool:
    return any(m in text for m in _MARKERS)


# Driver→GM plumbing that rides inside *user* messages but is not the
# player's words: the --refound tail wrapper and sawtooth baton nudges.
# Kept in sync with ui/drivers/claude_p.py and scriptorium.py.
_REFOUND_HEAD = "[OOC: Fresh session — re-founding from the baton."
_REFOUND_TAIL_END = "[OOC: end of tail — the player's next turn:]"
_SAW_NUDGE_PREFIX = "[OOC driver → GM:"


def _clean_player_text(text: str) -> str:
    if text.startswith(_REFOUND_HEAD) and _REFOUND_TAIL_END in text:
        text = text.split(_REFOUND_TAIL_END, 1)[1].strip()
    if _SAW_NUDGE_PREFIX in text:
        text = "\n".join(ln for ln in text.splitlines()
                         if not ln.strip().startswith(_SAW_NUDGE_PREFIX)).strip()
    return text


# Player-safe files whose name may appear in an activity line. Everything
# else — gm/**, state.md, arbitrary paths — is redacted to a generic verb,
# same discipline as the notary: surface the verb, never the hidden object.
def _safe_activity_target(path: str | None) -> str | None:
    if not path:
        return None
    norm = path.replace("\\", "/")
    base = os.path.basename(norm)
    if "/ui/drawers/" in norm:
        return f"the {os.path.splitext(base)[0].replace('-', ' ')} drawer"
    return {"surface.md": "the canon", "sheet.md": "the sheet",
            "map.md": "the map"}.get(base)  # gm/, state.md, etc. -> None


def classify_tool_activity(name: str, tool_input: dict):
    """Map a tool_use to a (verb, safe-target) the player may see. The verb
    is always safe; the target is only ever a player-visible file name."""
    name = name or ""
    inp = tool_input if isinstance(tool_input, dict) else {}
    if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return "writing", _safe_activity_target(inp.get("file_path") or inp.get("path"))
    if name in ("Read", "NotebookRead"):
        return "consulting", _safe_activity_target(inp.get("file_path"))
    if name == "Bash":
        cmd = inp.get("command") or ""
        if "roll.py" in cmd:
            return "rolling dice", None
        if re.search(r"\bgit\b", cmd):
            return "saving progress", None
        return "running a command", None
    if name in ("Grep", "Glob", "WebSearch"):
        return "searching", None
    if name == "WebFetch":
        return "reading a source", None
    return "using a tool", None


def parse_transcript_events(lines, skip_first_turn: bool, emit_activity: bool = False):
    """Yield player-safe events from raw JSONL lines.

    KEEP  : assistant `text` blocks  -> {"kind":"prose"}
            user string messages     -> {"kind":"turn"}   (the player's hand)
    DROP  : tool_result, system/meta, command echoes (tool_result is exactly
            where hidden gm/ content would leak).
    When emit_activity is set (live tail only, never the backlog snapshot),
    thinking/tool_use become ephemeral {"kind":"activity"} events carrying a
    redacted verb — the detail of what the model is doing, not its content.
    """
    seen_first_turn = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("isMeta") or obj.get("isCompactSummary"):
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")

        if role == "user":
            # Player turns arrive as plain strings. List content on the
            # user channel is tool_result (or command plumbing) — skip.
            if not isinstance(content, str):
                continue
            text = _clean_player_text(content.strip())
            if not text or _is_noise(text):
                continue
            if skip_first_turn and not seen_first_turn:
                # The first user string is the Baton launch / GM-boot
                # instruction, addressed to the model, not a player turn.
                seen_first_turn = True
                continue
            seen_first_turn = True
            yield {"kind": "turn", "text": text}

        elif role == "assistant":
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = (block.get("text") or "").strip()
                    if text and not _is_noise(text):
                        yield {"kind": "prose", "text": text}
                elif emit_activity and btype == "thinking":
                    yield {"kind": "activity", "verb": "reasoning", "target": None}
                elif emit_activity and btype == "tool_use":
                    verb, target = classify_tool_activity(block.get("name"), block.get("input"))
                    yield {"kind": "activity", "verb": verb, "target": target}


# ===========================================================================
# Story-file readers (all player-safe)
# ===========================================================================
def _section(markdown: str, heading_rx: str) -> str | None:
    """Return the body of the first matching '## Heading' section."""
    lines = markdown.splitlines()
    out, capturing = [], False
    for ln in lines:
        if re.match(r"^#{1,6}\s", ln):
            if capturing:
                break
            if re.match(heading_rx, ln, re.I):
                capturing = True
                continue
        elif capturing:
            out.append(ln)
    body = "\n".join(out).strip()
    return body or None


def read_story_title(story_dir: Path) -> str:
    surface = story_dir / "surface.md"
    if surface.exists():
        for ln in surface.read_text(errors="replace").splitlines():
            m = re.match(r"^#\s+(.*)", ln)
            if m:
                return m.group(1).strip()
    return story_dir.name


def read_resume(story_dir: Path):
    """Player-safe recap from surface.md '## Resume' — NEVER the baton."""
    surface = story_dir / "surface.md"
    if not surface.exists():
        return None
    body = _section(surface.read_text(errors="replace"), r"^##\s+Resume\b")
    if not body:
        return None
    # optional 'Next: ...' final line becomes the ribbon's next-beat
    where, nxt = body, None
    m = re.search(r"(?im)^\s*next:\s*(.+)$", body)
    if m:
        nxt = m.group(1).strip()
        where = body[: m.start()].strip()
    return {"where": where, "next": nxt}


# Built-in drawers map fixed keys to their canonical files. Their order is
# preserved; extra drawers (a story's ui/drawers/*.md) follow, alphabetical.
BUILTIN_DRAWERS = [("sheet", "sheet.md", "Sheet"),
                   ("canon", "surface.md", "Canon"),
                   ("map", "map.md", "Map")]


def _drawer_title(stem: str) -> str:
    return re.sub(r"[-_]+", " ", stem).strip().title()


def drawer_specs(story_dir: Path):
    """All drawers this story exposes right now, as
    (key, display-file, title, Path). A drawer exists iff its file does, so
    the UI shows exactly what's on disk — no hide rules, no dead tabs.
    Open-ended: drop any *.md into <story>/ui/drawers/ and it becomes a
    drawer. gm/ and state.md are never eligible (not in this set)."""
    specs = []
    for key, fname, title in BUILTIN_DRAWERS:
        p = story_dir / fname
        if p.exists():
            specs.append((key, fname, title, p))
    ddir = story_dir / "ui" / "drawers"
    if ddir.is_dir():
        for p in sorted(ddir.glob("*.md")):
            specs.append(("x-" + re.sub(r"[^a-z0-9]+", "-", p.stem.lower()).strip("-"),
                          f"drawers/{p.name}", _drawer_title(p.stem), p))
    return specs


def read_latest_roll(story_dir: Path):
    """Last line of the public rolls.log, parsed to dice/mod/total/note.
    Format: 'ISO | 2d6 | dice=[4, 3] mod=+0 | total=7 | why'."""
    log = story_dir / "rolls.log"
    if not log.exists():
        return None
    lines = [l for l in log.read_text(errors="replace").splitlines() if l.strip()]
    if not lines:
        return None
    parts = [p.strip() for p in lines[-1].split("|")]
    if len(parts) < 5:
        return None
    dice = [int(x) for x in re.findall(r"\d+", parts[2].split("mod")[0])]
    modm = re.search(r"mod=([+-]?\d+)", parts[2])
    totm = re.search(r"(\d+)", parts[3])
    return {
        "label": parts[1],
        "dice": dice,
        "mod": int(modm.group(1)) if modm else 0,
        "total": int(totm.group(1)) if totm else sum(dice),
        "note": parts[4],
    }


def list_illustrations(story_dir: Path) -> dict[str, float]:
    """Approved images under illustrations/ as {posix relpath: mtime}.
    queue/ (unrendered briefs) and pending/ (renders awaiting GM review)
    are excluded; only image files count."""
    root = story_dir / "illustrations"
    out: dict[str, float] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_TYPES:
            rel = p.relative_to(root).as_posix()
            if rel.split("/", 1)[0] not in UNSERVED_ILL:
                out[rel] = p.stat().st_mtime
    return out


def cast_entries(story_dir: Path) -> list[dict]:
    """The cast panel's data: one entry per portrait in illustrations/cast/.
    The display name is the filename stem, dashes to spaces, title-cased."""
    entries = []
    for rel in sorted(list_illustrations(story_dir)):
        parts = rel.split("/")
        if len(parts) == 2 and parts[0] == "cast":
            stem = os.path.splitext(parts[1])[0]
            name = re.sub(r"[-_]+", " ", stem).strip().title()
            entries.append({"name": name, "src": f"/story/illustrations/{rel}"})
    return entries


def read_notary(story_dir: Path):
    """Provenance WITHOUT content. mtime of gm/ hidden state → 'the world
    reacted, and when'; the git short-hash of the newest gm/ commit is the
    seal. gm/ file *contents* are never read."""
    gm = story_dir / "gm"
    if not gm.is_dir():
        return None
    newest = 0.0
    for p in gm.rglob("*"):
        if p.is_file():
            newest = max(newest, p.stat().st_mtime)
    seal = None
    try:
        import subprocess
        r = subprocess.run(
            ["git", "-C", str(story_dir), "log", "-1", "--format=%h", "--", "gm"],
            capture_output=True, text=True, timeout=3,
        )
        seal = r.stdout.strip() or None
    except Exception:
        pass
    when = time.strftime("%H:%M", time.localtime(newest)) if newest else ""
    return {"text": "hidden state logged", "seal": seal or "—", "time": when}


# ===========================================================================
# Event bus
# ===========================================================================
class Bus:
    def __init__(self):
        self._subs: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, event: str, data):
        payload = (event, data)
        with self._lock:
            for q in self._subs:
                q.put(payload)


# ===========================================================================
# Watcher — poll mtimes, tail the transcript, publish deltas
# ===========================================================================
class Watcher(threading.Thread):
    daemon = True

    def __init__(self, story_dir: Path, transcript: Path | None, bus: Bus,
                 skip_first: bool, explicit_session: str | None = None,
                 founding: bool = False):
        super().__init__()
        self.story = story_dir
        self.transcript = transcript
        self.bus = bus
        self.skip_first = skip_first
        self._explicit = explicit_session
        self.founding = founding
        self._mtimes: dict[str, float] = {}
        self._drawers: dict[str, float] = {}   # drawer key -> mtime
        self._ill: dict[str, float] = {}       # illustration relpath -> mtime
        self._busy: bool | None = None
        self._offset = 0
        self._first_scan_done = False

    def _mtime(self, path: Path) -> float:
        try:
            return path.stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def _changed(self, key: str, path: Path) -> bool:
        m = self._mtime(path)
        if self._mtimes.get(key) != m:
            self._mtimes[key] = m
            return True
        return False

    def snapshot(self):
        """Full current state for a freshly-connected client. Leads with a
        `reset` so a reconnecting EventSource clears before the replay
        (otherwise the stream would double)."""
        events = [("reset", {})]
        events.append(("meta", {"story": read_story_title(self.story)}))
        if self.founding:
            events.append(("founding", {"active": True, "name": read_story_title(self.story)}))
        resume = read_resume(self.story)
        if resume:
            events.append(("resume", resume))
        for key, file, title, p in drawer_specs(self.story):
            events.append(("drawer", {"which": key, "title": title, "file": file,
                                      "markdown": p.read_text(errors="replace")}))
        roll = read_latest_roll(self.story)
        if roll:
            events.append(("roll", roll))
        notary = read_notary(self.story)
        if notary:
            events.append(("notary", notary))
        cast = cast_entries(self.story)
        if cast:
            events.append(("cast", {"cast": cast}))
        inbox = self.story / ".baton" / "inbox"
        if inbox.is_dir() and list(inbox.glob("*.md")):
            events.append(("busy", {"active": True}))
        # story backlog from the transcript (filtered)
        if self.transcript and self.transcript.exists():
            lines = self.transcript.read_text(errors="replace").splitlines()
            for ev in parse_transcript_events(lines, self.skip_first):
                events.append(("story", ev))
        events.append(("session", {"state": "watching"}))
        return events

    def run(self):
        # prime transcript offset without emitting (snapshot handles backlog)
        if self.transcript and self.transcript.exists():
            self._offset = self.transcript.stat().st_size
        while True:
            try:
                self._tick()
            except Exception as e:  # never let the watcher die silently
                self.bus.publish("session", {"state": "error", "detail": str(e)})
            time.sleep(POLL_SECONDS)

    def _adopt(self, found: Path):
        """Point at `found` and prime the tail offset to its end. If clients
        are already connected (past the first scan), re-sync them with a full
        snapshot — a leading `reset` clears the stale session before the new
        backlog replays, so prose never doubles."""
        self.transcript = found
        if self._first_scan_done:
            for event, data in self.snapshot():
                self.bus.publish(event, data)
        self._offset = found.stat().st_size if found.exists() else 0

    def _sync_transcript(self):
        """Resolve which transcript to tail, and switch if it changed.

        - `--session` is authoritative and fixed: adopt it once it exists.
        - Otherwise a driver's `.baton/session` pointer wins: adopt it, and
          *switch* to it if it later names a different file than we're on
          (a live story already has an older transcript at startup, so the
          observer must be able to follow the driver's fresh session).
        - With no pointer we adopt the newest transcript once, then never
          switch on mtime alone — that would flap between concurrent runs."""
        if self._explicit:
            if self.transcript is None:
                found = find_transcript(self.story, self._explicit)
                if found:
                    self._adopt(found)
            return
        desired = find_transcript(self.story, None)
        if not desired:
            return
        if self.transcript is None:
            self._adopt(desired)
            return
        # Only a driver pointer justifies a mid-session switch.
        if (read_session_pointer(self.story)
                and desired.resolve() != self.transcript.resolve()):
            self._adopt(desired)

    def _tick(self):
        self._sync_transcript()
        # 1) drawers — set diff over built-ins + ui/drawers/*.md so files that
        #    appear, change, or vanish all propagate (added->create, gone->null).
        cur = {key: (p.stat().st_mtime, file, title, p)
               for key, file, title, p in drawer_specs(self.story)}
        if self._first_scan_done:
            for key in set(self._drawers) - set(cur):          # removed
                self.bus.publish("drawer", {"which": key, "markdown": None})
            for key, (m, file, title, p) in cur.items():        # added / changed
                if self._drawers.get(key) != m:
                    self.bus.publish("drawer", {"which": key, "title": title,
                                                "file": file, "markdown": p.read_text(errors="replace")})
                    if key == "canon":
                        r = read_resume(self.story)
                        if r:
                            self.bus.publish("resume", r)
                        self.bus.publish("meta", {"story": read_story_title(self.story)})
        self._drawers = {key: v[0] for key, v in cur.items()}
        # 2) public rolls
        if self._changed("rolls", self.story / "rolls.log") and self._first_scan_done:
            roll = read_latest_roll(self.story)
            if roll:
                self.bus.publish("roll", roll)
        # 3) notary — any change under gm/ (mtime only, never content)
        gm = self.story / "gm"
        gm_m = max([self._mtime(p) for p in gm.rglob("*") if p.is_file()], default=0.0) if gm.is_dir() else 0.0
        if self._mtimes.get("gm") != gm_m:
            self._mtimes["gm"] = gm_m
            if self._first_scan_done:
                n = read_notary(self.story)
                if n:
                    self.bus.publish("notary", n)
        # 3b) illustrations — new renders announce themselves (the client
        #     uses this to resolve "being illuminated…" placeholders), and
        #     a changed cast/ set refreshes the cast panel.
        ill = list_illustrations(self.story)
        if ill != self._ill:
            if self._first_scan_done:
                for rel in sorted(set(ill) - set(self._ill)):
                    self.bus.publish("illustration", {
                        "name": os.path.splitext(os.path.basename(rel))[0],
                        "src": f"/story/illustrations/{rel}"})
                old_cast = {k for k in self._ill if k.startswith("cast/")}
                new_cast = {k for k in ill if k.startswith("cast/")}
                if old_cast != new_cast:
                    self.bus.publish("cast", {"cast": cast_entries(self.story)})
            self._ill = ill
        # 4) busy — a turn is in flight while the inbox holds an unconsumed
        #    file (the driver moves it to done/ when the model finishes).
        inbox = self.story / ".baton" / "inbox"
        busy = bool(list(inbox.glob("*.md"))) if inbox.is_dir() else False
        if self._busy != busy:
            self._busy = busy
            if self._first_scan_done:
                self.bus.publish("busy", {"active": busy})
        # 5) transcript tail — story prose/turns, plus redacted activity detail
        if self.transcript and self.transcript.exists():
            size = self.transcript.stat().st_size
            if size > self._offset:
                with self.transcript.open("r", errors="replace") as fh:
                    fh.seek(self._offset)
                    chunk = fh.read()
                # only consume up to the last complete line
                nl = chunk.rfind("\n")
                if nl != -1:
                    consumed, chunk = chunk[: nl + 1], chunk[nl + 1:]
                    self._offset += len(consumed.encode("utf-8", "replace"))
                    if self._first_scan_done:
                        for ev in parse_transcript_events(consumed.splitlines(),
                                                          skip_first_turn=False, emit_activity=True):
                            if ev["kind"] == "activity":
                                self.bus.publish("activity", {"verb": ev["verb"], "target": ev["target"]})
                            else:
                                self.bus.publish("story", ev)
            elif size < self._offset:
                self._offset = 0  # file rotated / new session
        self._first_scan_done = True


# ===========================================================================
# HTTP
# ===========================================================================
def make_handler(story_dir: Path, bus: Bus, watcher: Watcher, inbox: Path):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        # ---- helpers ----
        def _send(self, code, ctype, body: bytes, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _serve_ui_asset(self, rel: str):
            # static UI assets live in baton/ui/, resolved safely.
            target = (UI_DIR / rel).resolve()
            if UI_DIR not in target.parents and target != UI_DIR:
                self._send(403, "text/plain", b"forbidden")
                return
            if not target.is_file():
                self._send(404, "text/plain", b"not found")
                return
            ctypes = {".html": "text/html", ".css": "text/css",
                      ".js": "application/javascript", ".json": "application/json"}
            ctype = ctypes.get(target.suffix, "application/octet-stream")
            self._send(200, ctype + "; charset=utf-8", target.read_bytes())

        def _serve_illustration(self, rel: str):
            """Images under <story>/illustrations/ only — never queue/,
            never pending/ (unreviewed renders), never the .md briefs. An
            extensionless request resolves to whichever image extension
            exists (the GM embeds extensionless, since it can't know what
            the renderer will produce)."""
            from urllib.parse import unquote
            rel = unquote(rel).strip("/")
            if (not rel or ".." in rel
                    or not re.fullmatch(r"[A-Za-z0-9._ \-/]+", rel)
                    or rel.split("/", 1)[0] in UNSERVED_ILL):
                self._send(403, "text/plain", b"forbidden"); return
            root = (story_dir / "illustrations").resolve()
            target = (root / rel).resolve()
            if not str(target).startswith(str(root) + os.sep):
                self._send(403, "text/plain", b"forbidden"); return
            candidates = ([target] if target.suffix else
                          [target.with_suffix(s) for s in IMAGE_TYPES])
            for c in candidates:
                if c.suffix.lower() in IMAGE_TYPES and c.is_file():
                    self._send(200, IMAGE_TYPES[c.suffix.lower()], c.read_bytes(),
                               extra={"Cache-Control": "max-age=300"})
                    return
            self._send(404, "text/plain", b"not found")

        def _serve_story_file(self, name: str):
            # membrane: allowlist only, no traversal, gm/ & state.md invisible.
            if name == "theme.css":
                target = (story_dir / "ui" / "theme.css")
            elif name in SERVED_FILES:
                target = (story_dir / name)
            else:
                self._send(403, "text/plain", b"forbidden"); return
            target = target.resolve()
            if not str(target).startswith(str(story_dir.resolve())):
                self._send(403, "text/plain", b"forbidden"); return
            if not target.is_file():
                self._send(404, "text/plain", b"not found"); return
            ctype = "text/css" if target.suffix == ".css" else "text/plain"
            self._send(200, ctype + "; charset=utf-8", target.read_bytes())

        # ---- routes ----
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._serve_ui_asset("index.html")
            elif path == "/events":
                self._events()
            elif path == "/story/theme.css":
                self._serve_story_file("theme.css")
            elif path.startswith("/story/illustrations/"):
                self._serve_illustration(path[len("/story/illustrations/"):])
            elif path.startswith("/story/"):
                self._serve_story_file(path[len("/story/"):])
            elif path in ("/styles.css", "/app.js", "/index.html") or path.startswith("/themes/"):
                self._serve_ui_asset(path.lstrip("/"))
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/input":
                self._send(404, "text/plain", b"not found"); return
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n) if n else b""
            try:
                text = json.loads(raw or b"{}").get("text", "").strip()
            except json.JSONDecodeError:
                text = ""
            if not text:
                self._send(400, "application/json", b'{"ok":false,"error":"empty"}'); return
            inbox.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%dT%H%M%S")
            # monotonic-ish unique name; ns avoids collisions within a second
            fn = inbox / f"{stamp}-{time.time_ns()}.md"
            fn.write_text(text + "\n")
            self._send(200, "application/json", json.dumps({"ok": True, "queued": fn.name}).encode())

        # ---- SSE ----
        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = bus.subscribe()
            try:
                for event, data in watcher.snapshot():
                    self._emit(event, data)
                while True:
                    try:
                        event, data = q.get(timeout=15)
                        self._emit(event, data)
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")  # comment ping
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                bus.unsubscribe(q)

        def _emit(self, event, data):
            msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
            self.wfile.write(msg.encode("utf-8"))
            self.wfile.flush()

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Baton UI observer backend")
    ap.add_argument("story", help="path to the story directory")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--session", help="explicit transcript .jsonl (default: auto-discover newest)")
    ap.add_argument("--skip-first-turn", action="store_true",
                    help="hide the first user message — use for INTERACTIVE sessions where it is "
                         "the GM-boot instruction, not a player turn. Leave off for driver "
                         "(claude -p) sessions, where the first user message is a real turn.")
    ap.add_argument("--no-scaffold", action="store_true",
                    help="do not scaffold an uninitialised directory; error instead")
    args = ap.parse_args()

    story = Path(args.story).resolve()
    founding = False
    if not is_founded(story):
        if args.no_scaffold:
            raise SystemExit(f"not a founded story: {story}")
        print(f"Founding new story at {story} …")
        if not scaffold_story(story):
            raise SystemExit("could not scaffold — no skeleton available")
        founding = True

    transcript = find_transcript(story, args.session)
    inbox = story / ".baton" / "inbox"

    bus = Bus()
    watcher = Watcher(story, transcript, bus, skip_first=args.skip_first_turn,
                      explicit_session=args.session, founding=founding)
    watcher.start()

    handler = make_handler(story, bus, watcher, inbox)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)

    print(f"Baton UI  ·  story: {story.name}{'  (FOUNDING)' if founding else ''}")
    print(f"  transcript: {transcript if transcript else '(none found — reading-only until a session writes one)'}")
    print(f"  inbox:      {inbox}")
    print(f"  serving:    http://{args.host}:{args.port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
