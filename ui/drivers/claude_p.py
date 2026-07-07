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


def sid_from_pointer(story: Path) -> str | None:
    """The pinned session id, recovered from <story>/.baton/session so a
    driver restart continues the same warm session instead of orphaning
    it. Returns None if the pointer is missing/empty or its transcript is
    gone."""
    ptr = story / ".baton" / "session"
    if not ptr.is_file():
        return None
    raw = ptr.read_text(errors="replace").strip()
    if not raw:
        return None
    p = Path(raw)
    return p.stem if p.exists() else None


def extract_stream(transcript: Path) -> list[tuple[str, str]]:
    """Player turns + narrator prose from a Claude Code transcript,
    filtered exactly like the observer: user *string* messages and
    assistant *text* blocks only. thinking / tool_use / tool_result are
    dropped — so the result is membrane-clean and, crucially,
    model-portable (no thinking blocks to replay into a fresh model)."""
    out: list[tuple[str, str]] = []
    try:
        lines = transcript.read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role == "user" and isinstance(content, str):
            t = content.strip()
            if t:
                out.append(("player", t))
        elif role == "assistant" and isinstance(content, list):
            texts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            joined = "\n".join(s for s in texts if s).strip()
            if joined:
                out.append(("narrator", joined))
    return out


def write_recent_tail(story: Path, transcript: Path, exchanges: int = 2) -> None:
    """Refresh <story>/.baton/recent.md with the last `exchanges` player
    turns and the narrator prose around them — the verbatim tail carried
    across a sawtooth re-found so tone and immediate context survive a
    reset that the (deliberately lossy) baton would launder away."""
    seq = extract_stream(transcript)
    if not seq:
        return
    player_idxs = [i for i, (r, _) in enumerate(seq) if r == "player"]
    if len(player_idxs) >= exchanges:
        start = player_idxs[-exchanges]
    elif player_idxs:
        start = player_idxs[0]
    else:
        start = 0
    parts = [
        "# recent — verbatim tail (auto-generated by the driver)",
        f"# last {exchanges} exchange(s), prose only, membrane-filtered.",
        "# carried across a --refound so the fresh session keeps the voice.",
        "",
    ]
    for role, text in seq[start:]:
        parts.append(f"**Player:**\n{text}\n" if role == "player"
                     else f"**Narrator:**\n{text}\n")
    (story / ".baton" / "recent.md").write_text("\n".join(parts) + "\n")


def wrap_refound_prompt(story: Path, text: str) -> str:
    """Prefix the first post-refound player turn with the verbatim tail,
    OOC-framed so the GM reads it as already-happened context (after it
    has loaded the baton + gm/ via the pickup protocol), not as new input.
    Returns `text` unchanged if there is no tail to inject."""
    recent = story / ".baton" / "recent.md"
    tail = recent.read_text(errors="replace").strip() if recent.is_file() else ""
    if not tail:
        return text
    return (
        "[OOC: Fresh session — re-founding from the baton. You have just "
        "loaded state.md (the baton) and gm/ via the pickup protocol. Below "
        "is the verbatim tail of the PREVIOUS session — the last couple of "
        "exchanges — given for tone and immediate continuity. It already "
        "happened; do not re-narrate or treat it as new player input. The "
        "player's actual next turn follows after the tail.]\n\n"
        f"{tail}\n\n"
        "[OOC: end of tail — the player's next turn:]\n\n"
        f"{text}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Baton claude -p driver — inbox → headless GM loop")
    ap.add_argument("story", help="path to the story directory")
    ap.add_argument("--resume", help="session id to continue. Default: auto-resume "
                    "the pinned session from .baton/session if present, else start "
                    "fresh on the first turn and pin it.")
    ap.add_argument("--refound", action="store_true",
                    help="ignore any warm session and re-found from the baton: start a "
                         "fresh session and inject the verbatim tail (.baton/recent.md, "
                         "the last 2 exchanges, prose-only) on the first turn. The "
                         "sawtooth reset — durable continuity is the baton + gm/ + tail, "
                         "on disk, not the session id.")
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
    inject_recent = False
    resume_note = None
    if args.refound:
        sid = None
        inject_recent = True
        resume_note = "re-founding from the baton (fresh session; verbatim tail injected on the first turn)"
    elif sid:
        resume_note = f"resuming session (--resume): {sid}"
    else:
        pinned = sid_from_pointer(story)
        if pinned:
            sid = pinned
            resume_note = f"auto-resumed pinned session (.baton/session): {sid}"
    printed_session = bool(sid)

    print(f"Baton claude -p driver  ·  inbox: {inbox}")
    print(f"  story: {story.name}   model: {args.model or '(default)'}   perm: {args.perm or '(default)'}")
    if resume_note:
        print(f"  {resume_note}")
    print("  (Ctrl-C to stop)")

    def project_slug() -> str:
        import re
        return re.sub(r"[^a-zA-Z0-9]", "-", str(story))

    def drain() -> int:
        nonlocal sid, printed_session, inject_recent
        turns = sorted(p for p in inbox.glob("*.md") if p.is_file())
        for p in turns:
            text = p.read_text(errors="replace").rstrip("\n")
            if not text:
                p.rename(done / p.name)
                continue
            print(f"  → turn {p.name}: {text[:60]!r}")
            send_text = text
            if inject_recent:
                send_text = wrap_refound_prompt(story, text)
                print("    ↻ re-founding: verbatim tail "
                      + ("injected from .baton/recent.md" if send_text != text
                         else "unavailable (clean fresh start)"))
            try:
                result = run_turn(story, send_text, sid, args.model, args.perm, extra)
            except Exception as e:
                print(f"    ! {e}")
                # leave the turn in the inbox to retry next tick
                return -1
            inject_recent = False  # only the first post-refound turn carries the tail
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
                # Keep the verbatim tail current so the next --refound is lossless.
                write_recent_tail(story, tpath)
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
