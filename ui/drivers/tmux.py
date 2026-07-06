#!/usr/bin/env python3
"""
Baton driver — tmux.

The reference inbox consumer. Watches <story>/.baton/inbox/ for player
turns dropped there by server.py, and types each into a running Claude
Code (or any REPL) session via `tmux send-keys`. Consumed turns move to
.baton/inbox/done/ so they are processed exactly once.

This is ONE driver. The inbox is a plain directory-queue, so other
drivers — claude -p, the Agents SDK, a remote/local model client — can
consume the same inbox independently, or instead. The server neither
knows nor cares which is running.

    # 1. launch the story session in a known tmux target:
    tmux new-session -s baton
    #    (inside it: cd <story> and start playing / claude)
    # 2. run the observer:
    python3 server.py <story> &
    # 3. run this driver, pointed at that target:
    python3 drivers/tmux.py <story> --target baton

The target is any tmux target-pane spec: 'session', 'session:win.pane'.

Stdlib only. tmux is the sole external dependency, and only for this
driver — not for Baton or the server.
"""

import argparse
import subprocess
import time
from pathlib import Path

POLL_SECONDS = 0.5


def tmux(*args) -> None:
    subprocess.run(["tmux", *args], check=True)


def deliver(target: str, text: str, submit_delay: float) -> None:
    """Type `text` into the target pane, then press Enter.

    send-keys -l sends the literal string (no key-name interpretation,
    so a turn containing 'Enter' or ';' is safe). Newlines in the turn
    are sent as literal newlines; a final Enter submits. The small delay
    lets a TUI (Claude Code) finish ingesting a multi-line paste before
    the submit keystroke lands."""
    # literal text (may contain newlines — send as one literal blob)
    tmux("send-keys", "-t", target, "-l", text)
    if submit_delay:
        time.sleep(submit_delay)
    tmux("send-keys", "-t", target, "Enter")


def main() -> None:
    ap = argparse.ArgumentParser(description="Baton tmux driver — inbox → tmux session")
    ap.add_argument("story", help="path to the story directory")
    ap.add_argument("--target", required=True, help="tmux target pane (e.g. 'baton' or 'baton:0.0')")
    ap.add_argument("--submit-delay", type=float, default=0.25,
                    help="seconds between typing the turn and pressing Enter (default 0.25)")
    ap.add_argument("--once", action="store_true", help="drain the inbox once and exit")
    args = ap.parse_args()

    story = Path(args.story).resolve()
    inbox = story / ".baton" / "inbox"
    done = inbox / "done"
    inbox.mkdir(parents=True, exist_ok=True)
    done.mkdir(parents=True, exist_ok=True)

    # verify the target exists early, with a clear error
    check = subprocess.run(["tmux", "has-session", "-t", args.target.split(":")[0]],
                           capture_output=True)
    if check.returncode != 0:
        raise SystemExit(f"tmux target not found: {args.target}\n"
                         f"Launch it first, e.g.  tmux new-session -s {args.target.split(':')[0]}")

    print(f"Baton tmux driver  ·  inbox: {inbox}")
    print(f"  target: {args.target}   (Ctrl-C to stop)")

    def drain() -> int:
        # process in filename order — timestamps sort chronologically
        turns = sorted(p for p in inbox.glob("*.md") if p.is_file())
        for p in turns:
            text = p.read_text(errors="replace").rstrip("\n")
            if text:
                print(f"  → delivering {p.name}: {text[:60]!r}")
                deliver(args.target, text, args.submit_delay)
            p.rename(done / p.name)
        return len(turns)

    if args.once:
        drain()
        return
    try:
        while True:
            drain()
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
