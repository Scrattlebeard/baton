# Baton

*A tiny framework for persistent, resumable, provably-fair interactive
stories with an LLM.*

Plain markdown, git, and one dice script. No dependencies, no schema,
no app. Built for [Claude Code](https://claude.com/claude-code) as the
reference runtime, but the conventions work with any LLM that can read
files and run shell commands.

**If you are an AI:** read [`AGENTS.md`](AGENTS.md) — the concrete
operating manual (the repo's `CLAUDE.md` imports it for Claude Code;
other runtimes should load it as the session's standing instruction).
This README is the *why*; AGENTS.md is the *do exactly this*.

## The three problems

1. **Persistence** — context windows end; long stories dissolve with
   them. Characters, world-state, and open threads need to live on
   disk, not in the conversation.
2. **Resumability** — state alone isn't enough. A session that resumes
   from a pile of facts re-establishes mood from scratch. What carries
   a story across the gap is *handoff with intent*: where we are, what
   is wanted next, what to deliver without re-earning. We call that
   note **the baton**, and it's the load-bearing feature the framework
   is named for.
3. **Fairness** — in rules-driven games, an LLM GM who improvises
   mechanics can't be honestly exploited: every "clever exploit" the
   player finds might just be the model deciding to reward cleverness.
   The fix is **precommitment**: the GM writes the rules *before* play
   and commits them to git. The hash proves the system was locked
   before the player touched it. Anything broken was broken fair.

## Three kinds of story, one spine

The kinds differ in **who owns world-truth**:

| kind | authority | extra files |
|---|---|---|
| **collaborative** | shared pen — canon is what the co-authors ratify | `register.md` — the agreed rules of physics/tone, cited instead of re-negotiated |
| **story-crawler** | GM owns the map, player owns the path (CYOA) | `gm/` — hidden state, honor-system: the player doesn't read it |
| **rules-game** | the rules document owns everyone, GM included (litRPG / progression) | `gm/rules.md` (the kernel, committed before play, hash published) + `sheet.md` + `gm/` |

All three share the spine: one directory per story, one git repo per
story, one mandatory `state.md` whose last section is always the baton.

## Layout

```
stories/
  CLAUDE.md                  # pickup protocol — auto-read on session start
  <story-name>/              # one git repo per story
    state.md                 # world-truth, cast, threads, flags, BATON
    surface.md               # player-visible canon
    sheet.md                 # character sheet (diegetic if you like)
    roll.py                  # fair dice; public rolls → rolls.log
    rolls.log
    gm/                      # hidden by agreement, not access control
      rules.md               # the kernel (rules-games)
      world.md               # sealed world-truth
      rulings.md             # append-only case law
      rolls.log              # hidden rolls (roll.py --gm)
```

Git does triple duty: **history** is the raw archive (every scene
survivable), **branches** are forks and save-states, **commit
timestamps** are the precommitment proof.

## The doctrine (rules-games)

The kernel is **consistent, not comprehensive** — a living document,
not an enumeration. What precommitment guarantees is *provenance, not
stasis*: every GM decision comes from a known regime.

- **Derived** — ruled from the kernel as committed. Auditable.
- **Elaborated** — new *additive* text (details, clarifications, a
  discovered interaction): a considered GM moment, logged to
  `gm/rulings.md` and committed the same session. Must be a
  conservative extension — nothing previously written *or played*
  becomes false.
- **Retconned** — changes committed words, or invalidates established
  events/setting (including what play has reasonably settled). Never a
  GM moment: always an open, out-of-game conversation. The GM never
  silently legislates under the player.
- **The timestamp test** — new world-truth may only color events
  *after* its commit time. To recolor the past, the text must already
  exist under seal in `gm/` *older than that past* — then it's a
  reveal, hash-provable. Written now, applied backwards = a retcon in
  elaboration's coat.

Four play principles keep it fun rather than adversarial:

- **Ecology test:** every exploit the player finds must survive *"why
  isn't this common knowledge / a dominant strategy?"* with a
  world-consistent answer — and every answer is a **door, not a wall**
  (the guild that manages it is *access*; the graveyard is *inferable
  knowledge*; a hidden cost implies windows where paying it is
  correct). If the player is genuinely first, it pays full freight.
  Cleverness is priced, never confiscated.
- **Anti-patch clause:** exploits get answered *in-world*, never
  nerfed retroactively. If advancement follows usage-shape rather than
  repetition, grinding produces narrow grinding-shaped growth — the
  world responds; the ledger doesn't get rewritten.
- **Foreshadow clause:** before any path turns costly, the world must
  have offered at least one legible signal. Signals may be missable —
  missing clues is play — but never absent.
- **Sealed rulings:** consequences can be committed hidden in `gm/`
  the moment they trigger and revealed sessions later — the seal holds
  both the consequence *and* the warning given, so the reveal proves
  the world reacted when it reacted and due process was on the page.
  Notarized fair play, not gotcha theater.

## Dice

`roll.py` (stdlib only) rolls `d20`, `2d6+1`, etc. using
`secrets`, appends every roll to a log, and you commit the log.
`--gm` sends a roll to the hidden log instead. No improvised numbers:
the audit trail is the point.

```
python3 roll.py 2d6+1 -l "climb the shelf-face"
```

## Quickstart

1. Copy `templates/CLAUDE.md` to your stories root (Claude Code reads
   it automatically when a session starts there; other runtimes: paste
   it as the session's first instruction).
2. Found a story: copy `templates/story-skeleton/` to
   `stories/<name>/`, `git init`, first commit. **Or start from an
   example** — `examples/` ships three ready-made surfaces, one per
   kind: `greenmarch/` (collaborative fantasy, walking-song mood),
   `neon-tithe/` (cyberpunk crawler romp), `folio/` (litRPG rules-game
   in a drowned library-city). See `examples/README.md`.
3. Co-design the *surface* together — setting, tone, what the player
   starts holding. Write it to `surface.md`.
4. **Rules-games:** the GM now works alone — writes `gm/rules.md` and
   `gm/world.md`, commits, and hands the player the hash. From that
   moment the kernel binds the GM.
5. Play. Log elaborations as they happen. Refresh the baton at every
   natural pause — endings are not guaranteed, and the baton is what
   makes that fact not matter.

## A browser UI (optional)

`ui/` is a small browser front-end — a read-mostly **observer** that
shows the player only what they may see. It turns the honor system into
an actual membrane: `gm/**` and `state.md` are never served, and the
model's tool calls and thinking are filtered out of the stream. Plain
HTML/CSS/JS + one stdlib Python server; no build step, no dependencies.
Full docs: [`ui/README.md`](ui/README.md).

**Start the observer** on a story (point it at an empty or absent
directory and it founds a new one — skeleton, `git init`, founding
commit — then serves it):

```
python3 ui/server.py stories/<name> --port 8765
# then open http://localhost:8765/
```

The composer drops each turn into `<story>/.baton/inbox/`; a **driver**
turns that into model input, and the driver is where you pick the model:

```
# headless `claude -p` loop (no tmux). --model selects the model:
python3 ui/drivers/claude_p.py stories/<name> \
    --model claude-haiku-4-5 --permission-mode acceptEdits

# …or feed turns into an interactive session in a tmux target:
python3 ui/drivers/tmux.py stories/<name> --target baton
```

Use any model id the `claude` CLI accepts — a cheap fast one
(`claude-haiku-4-5`) for co-design chatter, a heftier one for sealing a
kernel. The inbox is a plain queue, so drivers are swappable and
independent; without one running, the UI is still a live reading
surface and turns simply wait until a driver picks them up.

## On the honor system

`gm/` is hidden by agreement, not by access control — the player can
`cat` it any time and thereby end the game as a game. If you need hard
secrecy, a separate private repo or encryption works; but the trust is
rather the point, and the hashes exist so that trust never has to be
*blind*.

---

*Extracted 2026-07-05 from a working setup whose first story is still
running. The framework was proven before it was packaged: its own
design sessions were carried across context-window deaths by the exact
files it now templates.*
