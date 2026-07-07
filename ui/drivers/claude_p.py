#!/usr/bin/env python3
"""
Baton driver — claude -p.

Closes the loop with no tmux and no interactive session: it *is* the
game loop. Watches <story>/.baton/inbox/ for player turns and feeds each
to a headless `claude -p` invocation running in the story directory, so
the story's CLAUDE.md pickup protocol and gm/ context load exactly as
they would for a human GM. Continuity is a pinned session id: every turn
uses --resume <sid>, which appends to the same transcript file — the one
the observer (server.py) is already streaming to the browser.

    # 1. run the driver (it prints the session id + transcript path):
    python3 drivers/claude_p.py <story> --permission-mode acceptEdits
    # 2. point the observer at that session (or just start it — it will
    #    adopt the newest transcript once the first turn lands):
    python3 server.py <story> --session <printed-path>

A GM must read gm/, run roll.py, and commit — all tool use. In headless
mode that needs a permission policy; pass --permission-mode (e.g.
acceptEdits, or bypassPermissions for a fully trusted local loop) and/or
extra flags via --extra. Nothing here is baked in as policy.

This is ONE driver. The inbox is a plain directory-queue; tmux.py or any
other consumer can drive the same story instead. Stdlib + the `claude`
CLI only.
"""

import argparse
import json
import shlex
import subprocess
import time
from pathlib import Path

POLL_SECONDS = 0.5


def run_turn(story: Path, text: str, sid: str | None, model: str | None,
             perm: str | None, extra: list[str]) -> dict:
    """Invoke claude -p for one turn. Returns the parsed result JSON
    (includes session_id). Runs with cwd=story so context loads right and
    the transcript lands in the story's project slug."""
    cmd = ["claude", "-p", text, "--output-format", "json"]
    if sid:
        cmd += ["--resume", sid]
    if model:
        cmd += ["--model", model]
    if perm:
        cmd += ["--permission-mode", perm]
    cmd += extra
    proc = subprocess.run(cmd, cwd=str(story), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exited {proc.returncode}: {proc.stderr.strip()[:400]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        # last non-empty line is the most likely JSON payload
        for line in reversed(proc.stdout.splitlines()):
            if line.strip().startswith("{"):
                return json.loads(line)
        raise RuntimeError("could not parse claude -p JSON output")


def main() -> None:
    ap = argparse.ArgumentParser(description="Baton claude -p driver — inbox → headless GM loop")
    ap.add_argument("story", help="path to the story directory")
    ap.add_argument("--resume", help="session id to continue (default: start fresh on the first turn, then pin it)")
    ap.add_argument("--model", help="model id passed to claude -p")
    ap.add_argument("--permission-mode", dest="perm",
                    help="claude --permission-mode (e.g. acceptEdits, bypassPermissions). "
                         "A GM needs tool use; pick what you trust.")
    ap.add_argument("--extra", default="", help="extra args appended verbatim to every claude call")
    ap.add_argument("--once", action="store_true", help="drain the inbox once and exit")
    args = ap.parse_args()

    story = Path(args.story).resolve()
    inbox = story / ".baton" / "inbox"
    done = inbox / "done"
    inbox.mkdir(parents=True, exist_ok=True)
    done.mkdir(parents=True, exist_ok=True)
    extra = shlex.split(args.extra)

    sid = args.resume
    printed_session = bool(sid)

    print(f"Baton claude -p driver  ·  inbox: {inbox}")
    print(f"  story: {story.name}   model: {args.model or '(default)'}   perm: {args.perm or '(default)'}")
    if sid:
        print(f"  resuming session: {sid}")
    print("  (Ctrl-C to stop)")

    def project_slug() -> str:
        import re
        return re.sub(r"[^a-zA-Z0-9]", "-", str(story))

    def drain() -> int:
        nonlocal sid, printed_session
        turns = sorted(p for p in inbox.glob("*.md") if p.is_file())
        for p in turns:
            text = p.read_text(errors="replace").rstrip("\n")
            if not text:
                p.rename(done / p.name)
                continue
            print(f"  → turn {p.name}: {text[:60]!r}")
            try:
                result = run_turn(story, text, sid, args.model, args.perm, extra)
            except Exception as e:
                print(f"    ! {e}")
                # leave the turn in the inbox to retry next tick
                return -1
            new_sid = result.get("session_id")
            if new_sid:
                sid = new_sid
            if sid:
                # Pin the session for the observer: write the transcript path
                # to <story>/.baton/session. The observer prefers this pointer
                # over mtime-guessing, so it follows *this* session even when
                # older transcripts exist — start order stops mattering.
                tpath = Path.home() / ".claude" / "projects" / project_slug() / f"{sid}.jsonl"
                ptr = story / ".baton" / "session"
                want = f"{tpath}\n"
                if not ptr.exists() or ptr.read_text(errors="replace") != want:
                    ptr.write_text(want)
                if not printed_session:
                    print(f"    session pinned: {sid}")
                    print(f"    transcript:     {tpath}")
                    print(f"    → observer auto-adopts it via {ptr}")
                    print(f"      (or pin explicitly: python3 server.py {story} --session {tpath})")
                    printed_session = True
            snippet = (result.get("result") or "").strip().replace("\n", " ")
            print(f"    ✓ narrator replied ({len(snippet)} chars): {snippet[:70]!r}")
            p.rename(done / p.name)
        return len(turns)

    if args.once:
        drain()
        return
    try:
        while True:
            if drain() == -1:
                time.sleep(2.0)  # back off after an error
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
