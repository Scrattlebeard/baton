#!/usr/bin/env python3
"""
Baton scriptorium — the background loop.

Play happens in the main loop (a GM session fed by a driver). The
scriptorium is the monastery annex where everything that should NOT
block a player turn happens: copying the transcript into the story
repo (archiving), and — as jobs land — illumination (scene and cast
images) and quartermaster prep (future hooks, NPCs, locations, sealed
in gm/prep/ ahead of play). Housekeeping and preparation outside the
main loop.

    python3 scriptorium.py <story> --once          # one sweep
    python3 scriptorium.py <story> --interval 300  # keep sweeping

The treaty (two writers, one repository):
- The scriptorium reads committed story state and the harness
  transcripts; it WRITES only its own namespaces (archive/, later
  illustrations/ and gm/prep/). It never touches state.md, the baton,
  or anything else the GM's pen owns.
- It commits with an explicit pathspec (git commit -- <its paths>), so
  a GM change staged mid-turn is never swept into a scriptorium
  commit.
- Everything it produces is proposal-until-played: the GM session
  remains the only pen that makes things true in the story. (Prep
  committed here BEFORE play reaches it is sealed by timestamp — the
  background loop manufactures provable foresight as a byproduct.)

Jobs are small, idempotent functions; a sweep runs each enabled job
and commits whatever changed. Running two scriptoria, or a sweep with
nothing new, is a no-op.

Current jobs:
- archivist — regenerate archive/sessions/<sid>.md from every harness
  transcript of this story: prose only, membrane-filtered exactly like
  the observer and .baton/recent.md (no thinking, no tool use), with
  the --refound OOC tail-injection unwrapped so re-founded sessions
  don't archive a duplicated tail. Plus archive/sessions/index.md in
  chronological order. The story repo becomes its own raw archive —
  the prose survives even if the harness's transcript files are pruned.
- illustrator — render queued image briefs (illustrations/queue/*.md,
  body = prompt, optional leading `aspect: 16:9` / `model: ...` lines)
  via the Gemini image API (default model: nano-banana-2-lite /
  gemini-3.1-flash-lite-image; key from GOOGLE_API_KEY or
  GEMINI_API_KEY, .env supported). The image lands at the mirrored
  path under illustrations/ and the brief moves beside it as
  provenance. MEMBRANE RULE: briefs live in a player-visible
  namespace — write them from player-visible canon only, never from
  gm/ (the pixels leak whatever the prompt knew). A rendered name is
  never re-rendered, so cast portraits stay stable across sessions:
  one face per character, generated once, reused.

Stdlib only, like everything else here.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- shared

# Kept in sync with ui/drivers/claude_p.py (extract_stream) — the one
# membrane: user string messages and assistant text blocks only.

REFOUND_HEAD = "[OOC: Fresh session — re-founding from the baton."
REFOUND_TAIL_END = "[OOC: end of tail — the player's next turn:]"


def project_slug(story: Path) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", str(story))


def transcripts(story: Path) -> list[Path]:
    """Every harness transcript that ran in this story directory."""
    d = Path.home() / ".claude" / "projects" / project_slug(story)
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def unwrap_refound(text: str) -> str:
    """A --refound first turn arrives wrapped: OOC frame + verbatim tail
    + the player's actual turn. The tail is prose that already lives in
    the PREVIOUS session's archive — keep only the player's turn."""
    if text.startswith(REFOUND_HEAD) and REFOUND_TAIL_END in text:
        return text.split(REFOUND_TAIL_END, 1)[1].strip()
    return text


def extract_stream(transcript: Path) -> list[tuple[str, str, str]]:
    """(role, text, iso-timestamp) triples of player turns + narrator
    prose. thinking / tool_use / tool_result are dropped — membrane-clean
    and model-portable."""
    out: list[tuple[str, str, str]] = []
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
        ts = obj.get("timestamp") or ""
        role = msg.get("role")
        content = msg.get("content")
        if role == "user" and isinstance(content, str):
            t = unwrap_refound(content.strip())
            if t:
                out.append(("player", t, ts))
        elif role == "assistant" and isinstance(content, list):
            texts = [b.get("text", "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            joined = "\n".join(s for s in texts if s).strip()
            if joined:
                out.append(("narrator", joined, ts))
    return out


def commit_paths(story: Path, paths: list[Path], msg: str) -> bool:
    """Stage and commit ONLY the given paths (pathspec commit): a GM
    change staged concurrently in the same worktree stays out of this
    commit. Returns True if a commit was made."""
    rels = sorted({str(p.relative_to(story)) for p in paths})
    if not rels:
        return False
    subprocess.run(["git", "add", "--"] + rels, cwd=story, check=True,
                   capture_output=True)
    probe = subprocess.run(["git", "diff", "--cached", "--quiet", "--"] + rels,
                           cwd=story)
    if probe.returncode == 0:  # nothing actually changed
        return False
    subprocess.run(["git", "commit", "-m", msg, "--"] + rels, cwd=story,
                   check=True, capture_output=True)
    return True


# ------------------------------------------------------------------ jobs

def job_archivist(story: Path) -> tuple[list[Path], str]:
    """Regenerate archive/sessions/ from the harness transcripts.
    Idempotent: files are rewritten only when their content changed."""
    outdir = story / "archive" / "sessions"
    changed: list[Path] = []
    sessions: list[tuple[str, str, str, int]] = []  # (first_ts, sid, last_ts, n)
    for t in transcripts(story):
        seq = extract_stream(t)
        if not seq:
            continue
        sid = t.stem
        first_ts, last_ts = seq[0][2], seq[-1][2]
        n_player = sum(1 for r, _, _ in seq if r == "player")
        sessions.append((first_ts, sid, last_ts, n_player))
        parts = [
            f"# session {sid}",
            "",
            f"*Archived by the scriptorium — prose only, membrane-filtered "
            f"(no thinking, no tool use). {n_player} player turn(s), "
            f"{first_ts or '?'} → {last_ts or '?'}.*",
            "",
        ]
        for role, text, _ in seq:
            parts.append(f"**Player:**\n{text}\n" if role == "player"
                         else f"**Narrator:**\n{text}\n")
        content = "\n".join(parts) + "\n"
        f = outdir / f"{sid}.md"
        if not f.exists() or f.read_text(errors="replace") != content:
            outdir.mkdir(parents=True, exist_ok=True)
            f.write_text(content)
            changed.append(f)
    if sessions:
        sessions.sort()  # chronological by first turn
        parts = ["# archive — sessions in order", ""]
        for i, (first_ts, sid, last_ts, n_player) in enumerate(sessions, 1):
            day = (first_ts or "")[:10] or "????-??-??"
            parts.append(f"{i}. [{day} · {n_player} turn(s)]({sid}.md)")
        content = "\n".join(parts) + "\n"
        idx = outdir / "index.md"
        if not idx.exists() or idx.read_text(errors="replace") != content:
            outdir.mkdir(parents=True, exist_ok=True)
            idx.write_text(content)
            changed.append(idx)
    return changed, f"{len(changed)} file(s)" if changed else "up to date"


GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/"
              "models/{model}:generateContent")
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-lite-image"  # "Nano Banana 2 Lite"


def load_env(story: Path) -> dict:
    """KEY=VALUE lines from .env beside this script and .env in the
    story dir (story wins), then the real environment (which wins over
    both). No dependency on python-dotenv — this is a five-line parse."""
    env: dict[str, str] = {}
    for f in (Path(__file__).resolve().parent / ".env", story / ".env"):
        if f.is_file():
            for line in f.read_text(errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    env.update(os.environ)
    return env


def parse_brief(text: str) -> tuple[dict, str]:
    """Leading `key: value` lines (aspect / model) are config; the rest
    of the file is the prompt, verbatim."""
    cfg: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    for i, line in enumerate(lines + [""]):
        m = re.match(r"^(aspect|model)\s*:\s*(\S+)\s*$", line.strip())
        if m:
            cfg[m.group(1)] = m.group(2)
        elif line.strip():
            break
    return cfg, "\n".join(lines[i:]).strip()


def render_image(prompt: str, model: str, key: str,
                 aspect: str | None = None) -> tuple[bytes, str]:
    """One text-to-image call against the Gemini API (stdlib urllib).
    Returns (image bytes, mime type)."""
    gen_cfg: dict = {"responseModalities": ["IMAGE"]}
    if aspect:
        gen_cfg["imageConfig"] = {"aspectRatio": aspect}
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }).encode()
    req = urllib.request.Request(
        GEMINI_URL.format(model=model), data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.load(r)
    for cand in resp.get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []):
            blob = part.get("inlineData") or part.get("inline_data") or {}
            if blob.get("data"):
                mime = blob.get("mimeType") or blob.get("mime_type") or "image/png"
                return base64.b64decode(blob["data"]), mime
    raise RuntimeError("no image in response: " + json.dumps(resp)[:400])


def job_illustrator(story: Path) -> tuple[list[Path], str]:
    """Render queued image briefs. A brief is a markdown file at
    illustrations/queue/<path>.md whose body is the prompt (optional
    leading `aspect: 16:9` / `model: ...` lines). The image lands at
    illustrations/<path>.png|.jpg and the brief moves beside it as
    provenance. Failures leave the brief queued for the next sweep.
    An already-rendered name is never re-rendered (cast portraits stay
    stable): re-queue deliberately by deleting the image first."""
    queue = story / "illustrations" / "queue"
    briefs = [p for p in sorted(queue.rglob("*.md"))] if queue.is_dir() else []
    if not briefs:
        return [], "queue empty"
    env = load_env(story)
    key = env.get("GOOGLE_API_KEY") or env.get("GEMINI_API_KEY")
    if not key:
        return [], f"{len(briefs)} brief(s) queued, but no GOOGLE_API_KEY/GEMINI_API_KEY"
    rendered, failed, skipped = 0, 0, 0
    for brief in briefs:
        rel = brief.relative_to(queue)
        dest_md = story / "illustrations" / rel
        cfg, prompt = parse_brief(brief.read_text(errors="replace"))
        existing = [dest_md.with_suffix(s) for s in (".png", ".jpg")
                    if dest_md.with_suffix(s).exists()]
        if not prompt or existing:
            print(f"    illustrator: skip {rel} "
                  f"({'already rendered' if existing else 'empty brief'})")
            skipped += 1
            continue
        try:
            data, mime = render_image(prompt, cfg.get("model", DEFAULT_IMAGE_MODEL),
                                      key, cfg.get("aspect"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            print(f"    illustrator: FAILED {rel}: HTTP {e.code} {detail}")
            failed += 1
            continue
        except Exception as e:
            print(f"    illustrator: FAILED {rel}: {e}")
            failed += 1
            continue
        dest = dest_md.with_suffix(".jpg" if "jpeg" in mime else ".png")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest_md.write_text(brief.read_text(errors="replace"))
        brief.unlink()  # brief now lives beside its image as provenance
        print(f"    illustrator: rendered {dest.relative_to(story)} "
              f"({len(data) // 1024} KB)")
        rendered += 1
    note = f"rendered {rendered}, failed {failed}, skipped {skipped}"
    # One pathspec covers renders, moved briefs, AND queue deletions.
    return ([story / "illustrations"] if rendered or skipped else []), note


JOBS = {
    "archivist": job_archivist,
    "illustrator": job_illustrator,
}


# ------------------------------------------------------------------ main

def sweep(story: Path, jobs: list[str]) -> None:
    for name in jobs:
        changed, note = JOBS[name](story)
        if changed and commit_paths(
                story, changed,
                f"scriptorium: {name} — {note}"):
            print(f"  {name}: committed {note}")
        else:
            print(f"  {name}: {note}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Baton scriptorium — background housekeeping outside the main loop")
    ap.add_argument("story", help="path to the story directory")
    ap.add_argument("--jobs", default="archivist,illustrator",
                    help=f"comma-separated jobs to run "
                         f"(available: {', '.join(JOBS)}; default: all)")
    ap.add_argument("--interval", type=float, default=300.0,
                    help="seconds between sweeps (default 300)")
    ap.add_argument("--once", action="store_true", help="one sweep, then exit")
    args = ap.parse_args()

    story = Path(args.story).resolve()
    if not (story / "state.md").is_file():
        raise SystemExit(f"not a story (no state.md): {story}")
    jobs = [j.strip() for j in args.jobs.split(",") if j.strip()]
    unknown = [j for j in jobs if j not in JOBS]
    if unknown:
        raise SystemExit(f"unknown job(s): {', '.join(unknown)} "
                         f"(available: {', '.join(JOBS)})")

    print(f"Baton scriptorium  ·  story: {story.name}  ·  jobs: {', '.join(jobs)}")
    if args.once:
        sweep(story, jobs)
        return
    print(f"  sweeping every {args.interval:g}s  (Ctrl-C to stop)")
    try:
        while True:
            sweep(story, jobs)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
