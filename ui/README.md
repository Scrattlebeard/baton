# Baton UI

A browser viewport for a Baton story — with a **membrane**.

Baton stories are plain files played with an LLM. Played in a raw
terminal, the harness leaks: a tool-call preview flashes
`Read gm/world.md`, a thinking block muses about the sealed ending, and
the honor system that keeps `gm/` hidden is quietly betrayed. This UI
closes that gap. It is a read-mostly **observer**: it watches the story
directory and the session transcript and shows the player only what the
player is allowed to see — filtered structurally, not by luck.

It is a *book more than a chat app*: long-form prose, a bookmark-ribbon
resume, drawers backed by the story's own files, and a **notary line**
that proves the world reacted — when it reacted — without ever showing
what.

Plain HTML/CSS/JS + one stdlib Python server. No framework, no build
step, no dependencies. Same brand as Baton itself.

---

## Architecture

```
   browser (index.html + app.js)
      │  ▲
 POST │  │  Server-Sent Events  (prose, turns, rolls, drawers, notary,
/input│  │                       resume, founding, busy, activity)
/input│  │
      ▼  │
   server.py  ── observer ──►  reads: surface.md, sheet.md, map.md,
      │                               rolls.log, gm/ mtime+githash,
      │                               the session transcript (filtered)
      │
      └── writes ──►  <story>/.baton/inbox/<turn>.md
                              │
                              ▼
                        a DRIVER  (drivers/tmux.py, or claude -p,
                        or the Agents SDK, or any model client)
                              │
                              ▼
                     the story session  ──►  writes the transcript
                                              the observer is reading
```

The server does exactly two things and knows nothing about models:

1. **Read path** — streams player-safe events to the browser.
2. **Inbox write** — a player turn POSTed to `/input` is appended to
   `<story>/.baton/inbox/`. That's the end of the server's job.

Turning an inbox turn into model input is a **driver's** job,
deliberately decoupled. The inbox is a plain directory-queue, so
drivers are independent and swappable — run tmux today, an API client
tomorrow, without touching the server.

## The membrane — two layers

1. **Serving.** An allowlist: `surface.md`, `sheet.md`, `map.md`,
   `rolls.log`, and a story's own `ui/theme.css`. `gm/**` and
   `state.md` are never served; path traversal and encoded slashes are
   rejected.
2. **Transcript filter.** The observer tails the Claude Code session
   JSONL and forwards **only** assistant `text` blocks (narrator prose)
   and user string messages (player turns) as story content. `thinking`,
   `tool_use`, and `tool_result` never reach the story stream — and
   `tool_result` is *exactly* where a `cat gm/world.md` payload would
   ride. The filter keys on block type, so it can't be fooled by clever
   content. (`thinking`/`tool_use` are not wasted, though — their *type*
   becomes a redacted activity verb; see **Progress feedback**.)

**The boundary, named honestly.** The filter separates *channels*
(prose vs tool/thinking). It does **not** sanitize prose the GM chooses
to type. If a GM writes staging notes as player-facing narration, those
are visible — that is the honor system's domain, not the membrane's. A
GM playing *with* this UI keeps setup in `thinking` or `gm/`, where the
membrane already covers it.

## Notary

`gm/` changes are shown as provenance without content: the mtime of the
newest hidden file answers *"the world reacted, and when"*, and the git
short-hash of the latest commit touching `gm/` is the seal. The `gm/`
file contents are never read. This is the framework's timestamp-test
made visible in real time.

## Progress feedback

So a slow model never leaves the screen looking dead, two signals drive
a live "the narrator is …" indicator — both server-side, so any driver
lights them up identically:

- **`busy`** — a turn is in flight while the inbox holds an unconsumed
  file (the driver moves it to `done/` when the model finishes). Start
  and stop, reliable.
- **`activity`** — the *detail*, from the transcript's `thinking` and
  `tool_use` blocks, redacted the same way as the notary: the **verb**
  is surfaced, the **object** is not. `reasoning`, `rolling the dice`,
  `writing the canon` (a player-safe file may be named) — but a write to
  `gm/world.md` or `state.md` reads only `writing a file`. The
  classifier *names* the allowlist and redacts everything else, so it
  can't leak a hidden path it hasn't been told about.

The browser also echoes your turn the moment you send it (faded until
the transcript confirms it) so you never wait to see your own move.

## Resume ribbon

The ribbon reads a player-safe `## Resume` section from **surface.md**
— never the baton in `state.md`. In a crawler or rules-game the baton
is written *to the GM* and is full of spoilers; keeping the ribbon on
player canon is the safe, uniform rule. A GM who wants the ribbon adds
a short spoiler-free recap:

```markdown
## Resume
You left the drovers' road at dusk and came down to the ford in the rain.
Next: the miller is waiting for your answer.
```

A final `Next: …` line becomes the ribbon's next-beat. No `## Resume`,
no ribbon.

---

## Running

```bash
# 1. the observer (serves the UI, streams the story)
python3 ui/server.py /path/to/story --port 8765

# 2. open http://localhost:8765/

# 3. to advance the story from the browser, run a driver (pick one):

#    (a) claude -p — no tmux; the driver IS the game loop:
python3 ui/drivers/claude_p.py /path/to/story --permission-mode acceptEdits
#        it prints the session id + transcript path it pinned.
#        pick the model with --model (e.g. claude-opus-4-8[1m] for the
#        1M-context build); a headless GM needs its tool use allowed —
#        see § Permissions below.

#    (b) tmux — types turns into a running interactive session:
tmux new-session -s baton        # play / launch claude inside this
python3 ui/drivers/tmux.py /path/to/story --target baton
```

**Founding a new story.** Point the server at an empty or nonexistent
directory and it scaffolds one: copies the skeleton, `git init`, and
makes the founding commit (the first precommitment). The UI then shows a
founding banner instead of the resume ribbon — co-design `surface.md`
with the narrator, fill `sheet.md`, and for a rules-game the GM seals
`gm/` (its hash surfaces in the notary). An already-founded directory is
served as-is; pass `--no-scaffold` to refuse scaffolding and error
instead. *Note:* a rules-game's sealed authoring is GM-alone by doctrine
— do it off the player's observed channel; only the sealed hash should
cross back.

Without a driver the UI is a live **reading surface**: narrator prose,
drawers, rolls, and notary all update; player turns queue in the inbox
until a driver picks them up. That degraded mode is useful on its own.

**Which transcript the observer follows.** In priority order: an
explicit `--session /path/to/uuid.jsonl`; else a driver-written pointer
at `<story>/.baton/session`; else the newest transcript by mtime. The
`claude_p.py` driver writes that pointer when it pins its session, so
the observer follows *that* session even on a **live** story where older
transcripts already exist — and it switches to it the moment the pointer
appears, so start order between server and driver genuinely doesn't
matter. (Without a pointer the observer adopts the newest once and then
won't switch on mtime alone — that would flap between concurrent runs.)

**First-turn handling.** By default every message is shown. Interactive
sessions open with a GM-boot instruction on the user channel that isn't
a player turn — pass `--skip-first-turn` to hide it. Driver (`claude -p`)
sessions open with a *real* player turn, so leave the flag off.

**Continuity, and re-founding (the sawtooth).** The `claude_p.py`
driver's durable continuity is *not* the session id — it's the story on
disk: the baton in `state.md`, the `gm/` reference tier, and a short
verbatim tail the driver keeps in `.baton/recent.md` (the last two
exchanges, prose only, filtered exactly like the observer, so it carries
no thinking/tool blocks and stays model-portable). The warm
`claude -p --resume` session is only a cache on top of that. Two
consequences:

- **Auto-resume.** Restart the driver with no `--resume` and it reads
  `.baton/session` and continues the pinned session automatically — a
  lost session id is a no-op, not data loss.
- **`--refound`.** Ignore any warm session, start fresh, and inject the
  verbatim tail on the first turn (OOC-framed) so the new session
  re-founds from baton + `gm/` + tail with the voice intact. Use it to
  bound a days-long story's context before it balloons, or to switch
  models cleanly (a fresh session avoids replaying one model's thinking
  blocks into another). The reset is only as lossless as the baton is
  kept rich — which is the maintenance discipline AGENTS.md §4 already
  requires.

## Permissions — a headless GM needs its tool use

The `claude -p` driver runs with nobody at the keyboard, so every tool
call must be pre-authorized — and a GM does real tool work every turn:
it reads `gm/`, rolls with `roll.py`, edits `rulings.md` / `state.md`,
and commits. **`--permission-mode acceptEdits` covers the file writes
but not `Bash`**, so `roll.py` and `git commit` get denied with no one
to approve them — the GM silently can't roll or seal. Two ways to close
the gap:

- **Least-privilege (recommended).** Keep `acceptEdits` and drop a
  story-local `.claude/settings.local.json` allowing only the Bash the
  GM actually needs:

  ```json
  {
    "permissions": {
      "allow": [
        "Bash(python3 roll.py:*)",
        "Bash(git add:*)", "Bash(git commit:*)", "Bash(git status:*)",
        "Bash(git log:*)", "Bash(git diff:*)", "Bash(git show:*)",
        "Bash(git rev-parse:*)"
      ]
    }
  }
  ```

  Dice and commits work; arbitrary shell stays gated.

- **Fully trusted local loop.** `--permission-mode bypassPermissions`
  drops the gate entirely — simpler and broader, for when you trust the
  loop end to end.

The `tmux` driver needs none of this: it types into an interactive
session where you answer permission prompts yourself.

## Theming — one story, one skin

The UI reskins entirely from CSS custom properties. A story ships
`ui/theme.css` (served as `/story/theme.css`) that overrides any subset
of the tokens declared in `styles.css` — no markup changes. See
`themes/` for three worked examples (greenmarch, neon-tithe, folio) and
`design-brief.md` for the token contract.

## Drawers

The rail on the left holds one tab per drawer, built at runtime from what
exists on disk — a drawer with no backing file simply has no tab.

- **Built-in:** `sheet.md` → Sheet, `surface.md` → Canon, `map.md` → Map.
- **Open-ended:** drop any `*.md` into `<story>/ui/drawers/` and it becomes
  a drawer, titled from its filename (`the-guild.md` → "The Guild").
  Files appear, update, and disappear live. `gm/` and `state.md` are never
  eligible — only the built-in files and `ui/drawers/` are exposed.

## The inbox contract (for driver authors)

A driver watches `<story>/.baton/inbox/` and consumes `*.md` files:

- Each file is one player turn: raw UTF-8 text, filename is a sortable
  timestamp so chronological order = filename order.
- Claim a turn by processing it, then move it to
  `.baton/inbox/done/` (or delete it) so it's handled once.
- Feed the text to your model however you like; its output lands in the
  session transcript, which the observer already streams to the
  browser. A driver never talks to the server.
- *Optional but recommended:* write your session's transcript path to
  `<story>/.baton/session`. The observer prefers that pointer over
  mtime-guessing, so it follows your session even when older transcripts
  exist (see "Which transcript the observer follows"). `claude_p.py`
  does this; `tmux.py` doesn't (an interactive session is already the
  newest transcript, so mtime suffices).

That's the whole interface. `drivers/tmux.py` is ~90 lines and is the
canonical example.

## Files

| file | what |
|---|---|
| `server.py` | the observer backend (stdlib only) |
| `index.html` + `app.js` | the live app |
| `styles.css` | token contract + default theme + components |
| `themes/*.css` | three example story skins (the acid test) |
| `drivers/claude_p.py` | inbox consumer — headless `claude -p` game loop |
| `drivers/tmux.py` | inbox consumer — types turns into a tmux session |
| `design-brief.md` | the design handover |

## Out of scope (v1)

Asset / portrait generation · suggested-reply chips · cast panel is a
reserved placeholder · rendering `state.md` or `gm/` · auth ·
multi-story library view.
