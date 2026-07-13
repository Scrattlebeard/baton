#!/usr/bin/env python3
"""
Baton scriptorium — the background loop.

Play happens in the main loop (a GM session fed by a driver). The
scriptorium is the monastery annex where everything that should NOT
block a player turn happens: copying the transcript into the story
repo (archiving), and — as jobs land — illumination (scene and cast
images) and cellarer prep (future hooks, NPCs, locations, sealed
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
  body = prompt, optional leading `aspect:` / `model:` / `style: none`
  / `ref:` lines) via the Gemini image API (default model:
  nano-banana-2-lite / gemini-3.1-flash-lite-image; key from
  GOOGLE_API_KEY or GEMINI_API_KEY, .env supported). The image lands
  at the mirrored path under illustrations/ and the brief moves beside
  it as provenance. illustrations/style.md (the story's ratified
  house style — the visual register.md) is appended to every brief;
  `ref:` lines name approved images (extension optional) for
  image-to-image consistency — a brief whose ref is still pending
  waits in the queue. MEMBRANE RULE: briefs live in a player-visible
  namespace — write them from player-visible canon only, never from
  gm/ (the pixels leak whatever the prompt knew). A rendered name is
  never re-rendered, so cast portraits stay stable across sessions:
  one face per character, generated once, reused.
  GATING (image/facts reconciliation): renderers improvise — they add
  figures, doors, heraldry nobody briefed. In a gated story (crawler /
  rules-game by default, or --gated) renders land in
  illustrations/pending/, which is never served; the GM reviews each
  against canon and approves (git mv into place), adopts additions
  (logged to gm/rulings.md), or rejects and re-briefs. Collaborative
  stories default to freehand (--freehand): renders serve immediately
  and the shared pen ratifies or laughs. Doctrine: AGENTS.md §4.7.
- cellarer (opt-in: add it to --jobs) — draft forward material
  (hooks / NPCs / locations) into gm/prep/ between sessions via a
  headless `claude -p` call. Runs only when state.md has a new commit
  since its last run (a session happened), from an isolated cwd so its
  spoiler-laden transcript can never be archived into player-visible
  archive/. Proposals are sealed by commit before play reaches them —
  provable foresight as a byproduct — and are proposal-until-played:
  the GM may use, adapt, or discard; only play makes them true
  (AGENTS.md §5, the prep tier).

Stdlib only, like everything else here (the cellarer shells out
to the `claude` CLI, same as the drivers).
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
SAW_NUDGE_PREFIX = "[OOC driver → GM:"


def project_slug(story: Path) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", str(story))


def transcripts(story: Path) -> list[Path]:
    """Every harness transcript that ran in this story directory."""
    d = Path.home() / ".claude" / "projects" / project_slug(story)
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def unwrap_refound(text: str) -> str:
    """A --refound first turn arrives wrapped: OOC frame + verbatim tail
    + the player's actual turn. The tail is prose that already lives in
    the PREVIOUS session's archive — keep only the player's turn. Also
    drops sawtooth nudge lines (driver→GM plumbing, not the player's
    words); kept in sync with ui/drivers/claude_p.py and ui/server.py."""
    if text.startswith(REFOUND_HEAD) and REFOUND_TAIL_END in text:
        text = text.split(REFOUND_TAIL_END, 1)[1].strip()
    if SAW_NUDGE_PREFIX in text:
        text = "\n".join(ln for ln in text.splitlines()
                         if not ln.strip().startswith(SAW_NUDGE_PREFIX)).strip()
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

def job_archivist(story: Path, opts: dict) -> tuple[list[Path], str]:
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


CELLARER_PROMPT = """\
You are the CELLARER — the monastery's provisioner — for the story at \
{story}: the GM's background \
prep-hand, running between sessions. You are NOT the GM and you are NOT \
playing: nobody is speaking to you, no player is present, and any \
pickup-protocol instructions loaded from CLAUDE.md files do NOT apply to \
this run. Do not narrate, do not advance the story, do not touch dice.

Read, in order:
1. {story}/state.md — the baton and the OPEN THREADS are your work order.
2. Everything in {story}/gm/ — rules.md (binding constraints), world.md \
(sealed truth), rulings.md (case law), the durable reference files \
(cast.md, locations.md, ...), and any existing gm/prep/ files (so you \
extend rather than repeat).
3. {story}/surface.md and the most recent file or two in \
{story}/archive/sessions/ — for voice, tone, and what play actually \
established.

Then draft 2-4 PROPOSALS into {story}/gm/prep/ — forward material the GM \
may draw on next session:
- hooks that complicate or advance an OPEN thread (never resolve one — \
prep offers doors, not outcomes),
- NPCs the story plausibly routes toward,
- locations that could anchor a thread.

File conventions, follow exactly:
- Append to topic files: gm/prep/hooks.md, gm/prep/npcs.md, \
gm/prep/locations.md (create a file only when you have an entry for it). \
APPEND-ONLY: never rewrite, reorder, or delete existing prep entries — \
each entry's commit is its proof of foresight, and editing history \
breaks the seal.
- Each entry: a heading `## <name> — proposed <today's date>`, then: \
one-line essence; the durable facts; which open thread it serves and \
how; at least one legible FORESHADOW SIGNAL the world could show before \
this material turns costly for the player; any hidden truth on lines \
marked [SEALED].
- Conservative extension only: nothing written in gm/ and nothing \
established in play may become false. If you are unsure whether \
something is established, leave it out.
- Proposals are NOT canon. The GM may use, adapt, or discard them \
freely; only play makes them true. Write offers, not commitments.
- Write ONLY inside {story}/gm/prep/. Do not modify any other file. Do \
not run git — the scriptorium commits your work.

End with a one-line summary of what you drafted (it is logged for the \
GM, never shown to a player).
"""

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
    """Leading `key: value` lines are config; the rest of the file is
    the prompt, verbatim. Keys: aspect, model, style (`style: none`
    opts this brief out of the house style), ref (repeatable — a
    reference image path relative to illustrations/, e.g.
    `ref: cast/the-miller`, extension optional)."""
    cfg: dict = {"ref": []}
    lines = text.splitlines()
    i = 0
    for i, line in enumerate(lines + [""]):
        m = re.match(r"^(aspect|model|style|ref)\s*:\s*(.+?)\s*$", line.strip())
        if m:
            if m.group(1) == "ref":
                cfg["ref"].append(m.group(2))
            else:
                cfg[m.group(1)] = m.group(2)
        elif line.strip():
            break
    return cfg, "\n".join(lines[i:]).strip()


def read_house_style(story: Path) -> str:
    """illustrations/style.md — the story's ratified visual register,
    appended to every brief so all renders share one look. The visual
    analog of a collaborative story's register.md."""
    f = story / "illustrations" / "style.md"
    return f.read_text(errors="replace").strip() if f.is_file() else ""


def resolve_refs(story: Path, names: list[str]) -> list[Path] | None:
    """Brief `ref:` lines → live image paths under illustrations/
    (extensionless resolves; queue/ and pending/ never count — a ref
    must be APPROVED canon). Returns None if any ref is missing, so
    the brief waits in the queue until e.g. its cast portrait clears
    the gate."""
    root = story / "illustrations"
    out: list[Path] = []
    for name in names:
        name = name.strip().lstrip("/")
        if ".." in name or name.split("/", 1)[0] in ("queue", "pending"):
            return None
        p = root / name
        cands = [p] if p.suffix else [p.with_suffix(s) for s in (".png", ".jpg")]
        found = next((c for c in cands if c.is_file()), None)
        if not found:
            return None
        out.append(found)
    return out


REF_MIMES = {".png": "image/png", ".jpg": "image/jpeg"}


def render_image(prompt: str, model: str, key: str,
                 aspect: str | None = None,
                 refs: list[Path] | None = None) -> tuple[bytes, str]:
    """One image call against the Gemini API (stdlib urllib), optionally
    image-to-image with reference images. Returns (image bytes, mime)."""
    gen_cfg: dict = {"responseModalities": ["IMAGE"]}
    if aspect:
        gen_cfg["imageConfig"] = {"aspectRatio": aspect}
    parts: list[dict] = [{"inline_data": {
        "mime_type": REF_MIMES[r.suffix.lower()],
        "data": base64.b64encode(r.read_bytes()).decode()}} for r in refs or []]
    parts.append({"text": prompt})
    body = json.dumps({
        "contents": [{"parts": parts}],
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


def story_is_gated(story: Path, opts: dict) -> bool:
    """Gated = renders land in illustrations/pending/ (not served) until
    the GM reviews them against canon and approves (git mv into place).
    Default follows who owns world-truth: only `collaborative` stories
    (shared pen — a wild render is just another suggestion to ratify)
    run freehand; crawler / rules-game / unknown are gated. CLI
    --gated/--freehand overrides."""
    if opts.get("gate") is not None:
        return opts["gate"]
    st = story / "state.md"
    kind = ""
    if st.is_file():
        m = re.search(r"^\*\*Kind:\*\*\s*(.+)$",
                      st.read_text(errors="replace"), re.M)
        if m:
            kind = m.group(1).strip().lower()
    return kind != "collaborative"


def job_illustrator(story: Path, opts: dict) -> tuple[list[Path], str]:
    """Render queued image briefs. A brief is a markdown file at
    illustrations/queue/<path>.md whose body is the prompt (optional
    leading `aspect: 16:9` / `model: ...` lines). The rendered image
    lands at illustrations/<path>.png|.jpg — or, in a GATED story, at
    illustrations/pending/<path>.png|.jpg to await the GM's
    image/facts reconciliation (see AGENTS.md) — with the brief moved
    beside it as provenance. Failures leave the brief queued for the
    next sweep. An already-rendered name (live OR pending) is never
    re-rendered, so cast portraits stay stable: re-render deliberately
    by deleting the image first."""
    queue = story / "illustrations" / "queue"
    briefs = [p for p in sorted(queue.rglob("*.md"))] if queue.is_dir() else []
    if not briefs:
        return [], "queue empty"
    env = load_env(story)
    key = env.get("GOOGLE_API_KEY") or env.get("GEMINI_API_KEY")
    if not key:
        return [], f"{len(briefs)} brief(s) queued, but no GOOGLE_API_KEY/GEMINI_API_KEY"
    gated = story_is_gated(story, opts)
    style = read_house_style(story)
    dest_root = story / "illustrations" / ("pending" if gated else "")
    rendered, failed, skipped = 0, 0, 0
    for brief in briefs:
        rel = brief.relative_to(queue)
        dest_md = dest_root / rel
        cfg, prompt = parse_brief(brief.read_text(errors="replace"))
        existing = [base.with_suffix(s)
                    for base in (story / "illustrations" / rel,
                                 story / "illustrations" / "pending" / rel)
                    for s in (".png", ".jpg")
                    if base.with_suffix(s).exists()]
        if not prompt or existing:
            print(f"    illustrator: skip {rel} "
                  f"({'already rendered' if existing else 'empty brief'})")
            skipped += 1
            continue
        refs = resolve_refs(story, cfg["ref"])
        if refs is None:
            # a named ref isn't approved canon yet — the brief waits
            print(f"    illustrator: waiting {rel} (ref not yet available: "
                  f"{', '.join(cfg['ref'])})")
            skipped += 1
            continue
        full_prompt = prompt
        if style and cfg.get("style", "").lower() != "none":
            full_prompt = f"{prompt}\n\nHouse style (applies to every " \
                          f"illustration in this story):\n{style}"
        try:
            data, mime = render_image(full_prompt,
                                      cfg.get("model", DEFAULT_IMAGE_MODEL),
                                      key, cfg.get("aspect"), refs)
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
              f"({len(data) // 1024} KB)"
              + ("  [pending GM review]" if gated else ""))
        rendered += 1
    note = (f"rendered {rendered}{' to pending/' if gated and rendered else ''}, "
            f"failed {failed}, skipped {skipped}")
    # One pathspec covers renders, moved briefs, AND queue deletions.
    return ([story / "illustrations"] if rendered or skipped else []), note


def job_cellarer(story: Path, opts: dict) -> tuple[list[Path], str]:
    """Draft forward material (hooks / NPCs / locations) into gm/prep/
    between sessions, via a headless `claude -p` call. Proposals are
    sealed by their commit timestamp before play reaches them —
    provable foresight as a byproduct — and are NOT canon until the GM
    plays them (AGENTS.md §5, the prep tier).

    Trigger: runs only when state.md's last commit differs from the one
    recorded at the previous successful run (new baton = a session
    happened = prep is worth an LLM call). Marker: .baton/cellarer.last.

    Isolation: the call runs with cwd=<story>/.baton/cellarer/ —
    a different project slug — so its spoiler-laden transcript (it reads
    gm/world.md) can never be swept into player-visible archive/ by the
    archivist. Story access goes through --add-dir; no Bash tool, so it
    cannot commit or roll — it can only read and write files."""
    probe = subprocess.run(["git", "log", "-1", "--format=%H", "--", "state.md"],
                           cwd=story, capture_output=True, text=True)
    head = probe.stdout.strip()
    if not head:
        return [], "no committed state.md yet (found a session first)"
    marker = story / ".baton" / "cellarer.last"
    legacy = story / ".baton" / "quartermaster.last"  # pre-rename marker
    last = (marker.read_text().strip() if marker.is_file()
            else legacy.read_text().strip() if legacy.is_file() else "")
    if head == last and not opts.get("prep_force"):
        return [], "no new session since last prep (state.md unchanged)"
    workdir = story / ".baton" / "cellarer"
    workdir.mkdir(parents=True, exist_ok=True)
    prep = story / "gm" / "prep"
    before = {p: p.stat().st_mtime for p in prep.rglob("*.md")} if prep.is_dir() else {}
    cmd = ["claude", "-p", CELLARER_PROMPT.format(story=story),
           "--output-format", "json",
           "--permission-mode", "acceptEdits",
           "--add-dir", str(story),
           "--allowedTools", "Read,Write,Edit,Glob,Grep"]
    if opts.get("prep_model"):
        cmd += ["--model", opts["prep_model"]]
    try:
        proc = subprocess.run(cmd, cwd=workdir, capture_output=True,
                              text=True, timeout=900)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return [], f"claude -p unavailable/timed out ({e}); will retry"
    if proc.returncode != 0:
        return [], (f"claude -p exited {proc.returncode}: "
                    f"{proc.stderr.strip()[:200]}; will retry")
    summary = ""
    try:
        summary = (json.loads(proc.stdout).get("result") or "").strip()
    except json.JSONDecodeError:
        pass
    after = {p: p.stat().st_mtime for p in prep.rglob("*.md")} if prep.is_dir() else {}
    changed = [p for p in after if before.get(p) != after[p]]
    marker.write_text(head + "\n")
    first_line = summary.splitlines()[0][:120] if summary else "no summary"
    if not changed:
        return [], f"ran but drafted nothing ({first_line})"
    print(f"    cellarer: {first_line}")
    return [prep], f"{len(changed)} prep file(s) touched — {first_line}"


JOBS = {
    "archivist": job_archivist,
    "illustrator": job_illustrator,
    "cellarer": job_cellarer,
    "quartermaster": job_cellarer,  # alias — the soldier's name still opens the pantry
}


# ------------------------------------------------------------------ main

def sweep(story: Path, jobs: list[str], opts: dict) -> None:
    for name in jobs:
        changed, note = JOBS[name](story, opts)
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
    gate = ap.add_mutually_exclusive_group()
    gate.add_argument("--gated", dest="gate", action="store_true", default=None,
                      help="force renders into illustrations/pending/ for GM "
                           "review (default for crawler / rules-game stories)")
    gate.add_argument("--freehand", dest="gate", action="store_false",
                      help="serve renders immediately, no review "
                           "(default for collaborative stories)")
    ap.add_argument("--prep-model",
                    help="model id for the cellarer's claude -p call "
                         "(default: the claude CLI's default)")
    ap.add_argument("--prep-force", action="store_true",
                    help="run the cellarer even if state.md is unchanged "
                         "since its last run")
    args = ap.parse_args()

    story = Path(args.story).resolve()
    if not (story / "state.md").is_file():
        raise SystemExit(f"not a story (no state.md): {story}")
    jobs = [j.strip() for j in args.jobs.split(",") if j.strip()]
    unknown = [j for j in jobs if j not in JOBS]
    if unknown:
        raise SystemExit(f"unknown job(s): {', '.join(unknown)} "
                         f"(available: {', '.join(JOBS)})")

    opts = {"gate": args.gate, "prep_model": args.prep_model,
            "prep_force": args.prep_force}
    mode = "gated" if story_is_gated(story, opts) else "freehand"
    print(f"Baton scriptorium  ·  story: {story.name}  ·  jobs: {', '.join(jobs)}"
          f"  ·  illustrations: {mode}")
    if args.once:
        sweep(story, jobs, opts)
        return
    print(f"  sweeping every {args.interval:g}s  (Ctrl-C to stop)")
    try:
        while True:
            sweep(story, jobs, opts)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
