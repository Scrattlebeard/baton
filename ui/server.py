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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# The membrane. Only these basenames are ever served from the story dir.
# Everything else — gm/**, state.md, roll.py, .git, .baton — is invisible.
# ---------------------------------------------------------------------------
SERVED_FILES = {"surface.md", "sheet.md", "map.md", "rolls.log", "theme.css"}
# theme.css is looked up at <story>/ui/theme.css (a story's own skin).

POLL_SECONDS = 0.5


# ===========================================================================
# Transcript: locate + filter
# ===========================================================================
def project_slug(story_dir: Path) -> str:
    """Claude Code stores transcripts under ~/.claude/projects/<slug>/,
    where <slug> is the absolute cwd with every non-alphanumeric run
    replaced by a dash. Verified against live dirs."""
    return re.sub(r"[^a-zA-Z0-9]", "-", str(story_dir.resolve()))


def find_transcript(story_dir: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    proj = Path.home() / ".claude" / "projects" / project_slug(story_dir)
    if not proj.is_dir():
        return None
    jsonls = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonls[0] if jsonls else None


_MARKERS = ("<command-name>", "<local-command", "system-reminder",
            "<command-message>", "<command-args>")


def _is_noise(text: str) -> bool:
    return any(m in text for m in _MARKERS)


def parse_transcript_events(lines, skip_first_turn: bool):
    """Yield player-safe story events from raw JSONL lines.

    KEEP  : assistant `text` blocks  -> {"kind":"prose"}
            user string messages     -> {"kind":"turn"}   (the player's hand)
    DROP  : thinking, tool_use, tool_result, system/meta, command echoes.
            tool_result is dropped both because it isn't story text AND
            because it is exactly where hidden gm/ content would leak.
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
            text = content.strip()
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
                if block.get("type") == "text":
                    text = (block.get("text") or "").strip()
                    if text and not _is_noise(text):
                        yield {"kind": "prose", "text": text}
                # thinking / tool_use are intentionally ignored.


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


def read_drawer(story_dir: Path, which: str):
    fname = {"sheet": "sheet.md", "canon": "surface.md", "map": "map.md"}[which]
    f = story_dir / fname
    return f.read_text(errors="replace") if f.exists() else None


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
                 skip_first: bool, explicit_session: str | None = None):
        super().__init__()
        self.story = story_dir
        self.transcript = transcript
        self.bus = bus
        self.skip_first = skip_first
        self._explicit = explicit_session
        self._mtimes: dict[str, float] = {}
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
        resume = read_resume(self.story)
        if resume:
            events.append(("resume", resume))
        for which in ("sheet", "canon", "map"):
            md = read_drawer(self.story, which)
            events.append(("drawer", {"which": which, "markdown": md}))
        roll = read_latest_roll(self.story)
        if roll:
            events.append(("roll", roll))
        notary = read_notary(self.story)
        if notary:
            events.append(("notary", notary))
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

    def _adopt_transcript_if_needed(self):
        """If we have no transcript yet (observer started before any session
        existed — e.g. before a driver's first turn), keep looking. Once one
        appears, adopt it and replay its backlog to connected clients. Only
        fires while transcript is None, so it never switches mid-session."""
        if self.transcript and self.transcript.exists():
            return
        found = find_transcript(self.story, self._explicit)
        if not found:
            return
        self.transcript = found
        if self._first_scan_done:
            lines = found.read_text(errors="replace").splitlines()
            for ev in parse_transcript_events(lines, self.skip_first):
                self.bus.publish("story", ev)
        self._offset = found.stat().st_size

    def _tick(self):
        self._adopt_transcript_if_needed()
        # 1) drawers
        for which, fname in (("sheet", "sheet.md"), ("canon", "surface.md"), ("map", "map.md")):
            if self._changed(f"drawer:{which}", self.story / fname):
                if self._first_scan_done:
                    self.bus.publish("drawer", {"which": which, "markdown": read_drawer(self.story, which)})
                    if which == "canon":
                        r = read_resume(self.story)
                        if r:
                            self.bus.publish("resume", r)
                        self.bus.publish("meta", {"story": read_story_title(self.story)})
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
        # 4) transcript tail
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
                        for ev in parse_transcript_events(consumed.splitlines(), skip_first_turn=False):
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
    args = ap.parse_args()

    story = Path(args.story).resolve()
    if not story.is_dir():
        raise SystemExit(f"not a directory: {story}")

    transcript = find_transcript(story, args.session)
    inbox = story / ".baton" / "inbox"

    bus = Bus()
    watcher = Watcher(story, transcript, bus, skip_first=args.skip_first_turn,
                      explicit_session=args.session)
    watcher.start()

    handler = make_handler(story, bus, watcher, inbox)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)

    print(f"Baton UI  ·  story: {story.name}")
    print(f"  transcript: {transcript if transcript else '(none found — reading-only until a session writes one)'}")
    print(f"  inbox:      {inbox}")
    print(f"  serving:    http://{args.host}:{args.port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
