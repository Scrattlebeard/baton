# stories — pickup protocol

This directory holds interactive stories: play known as play, one git
repo per story. Framework conventions: see the Baton README.

**On session start inside a story directory:**
1. Read that story's `state.md` FIRST — the baton section at the end
   tells you where the story stands and what is wanted next. Honor it;
   deliver, don't re-establish.
2. Read the player-visible canon (`surface.md`, `sheet.md` if present).
3. If you are the GM (rules-game or story-crawler): read `gm/` — the
   rules kernel, sealed world-truth, and case law. The kernel is
   BINDING on you from its committed hash. `gm/` is hidden from the
   player by agreement; never quote it to them.
4. Play. Log elaborations to `gm/rulings.md` as they happen; update
   `state.md` (especially the baton) before the session ends — and at
   every natural pause, since endings are not guaranteed.

**Dice:** use the story's `roll.py` (`python3 roll.py 2d6+1 -l "why"`),
never improvised numbers. Public rolls log to `rolls.log`, GM rolls to
`gm/rolls.log` via `--gm`. Commit the logs — fairness is auditable.

**Commit discipline:** commit at every meaningful state change
(rulings, seals, session ends). Hashes are load-bearing: they prove
precommitment — sealed reveals may only color events younger than
their commit (the timestamp test), and retcons never happen silently;
they are an open, out-of-game conversation.
