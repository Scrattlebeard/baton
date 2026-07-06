# Baton UI — design handover

*Brief for Claude Design. Scope: the look and the theming system, not
the backend. Written 2026-07-06; decisions herein are ratified.*

## What Baton is (60 seconds)

Baton is a tiny framework for persistent, resumable, provably-fair
interactive stories played with an LLM. A story is a directory: plain
markdown files, a git repo, one dice script. The LLM is narrator or GM;
the human is co-author or player. Fairness is enforced by
precommitment — hidden GM state lives in `gm/`, sealed by git hashes
that prove the rules existed before the player touched them.

The repo is public. The whole brand is: **no app, no schema, no
dependencies — plain files and git.** The UI must feel like a natural
outgrowth of that, not a product bolted on top.

## What this UI is

A **viewport with a membrane**. The backend watches a story directory
and serves only the player-visible files; `gm/**` is never served —
the honor system becomes real access control. The model's tool calls
and thinking are filtered out of the stream; the player sees only
story prose. The UI never owns state — a terminal session on the same
story can coexist with it.

It is **a book more than a chat app.** Sessions are long-form fiction
read in sittings. Reading comfort is the center of gravity; chrome
recedes.

## Layout (desktop-first, degrade gracefully)

```
┌────────────────────────────────────────────┬──────────────┐
│                                            │  CAST PANEL  │
│   STORY STREAM                             │  (pinned,    │
│   long-form prose, player turns,           │  placeholder │
│   scene breaks                             │  for now)    │
│                                            ├──────────────┤
│                                            │  DRAWERS     │
│                                            │  ▸ Sheet     │
│                                            │  ▸ Canon     │
│                                            │  ▸ Map       │
├────────────────────────────────────────────┤              │
│   NOTARY TICKER (one quiet line)           │              │
├────────────────────────────────────────────┴──────────────┤
│   COMPOSER — freeform text input                          │
└───────────────────────────────────────────────────────────┘
```

- **Story stream** — rendered markdown prose from the model,
  interleaved with the player's turns (visually distinct but not
  chat-bubbly; think manuscript margins, not messaging app). Scene
  breaks as typographic ornaments. Streams token-by-token.
- **Composer** — freeform text only (v1 decision). Multiline,
  unobtrusive. Future: suggested-reply chips; leave room, don't build.
- **Notary ticker** — a single quiet line for spoiler-free GM
  provenance: *"🎲 hidden roll logged · sealed ruling committed
  `a3f9c12`"*. This is the fairness doctrine made visible: the player
  sees **that** the world reacted and **when**, never *what*. Should
  read as notarization, not activity noise. Public rolls can render
  richer (dice faces, modifier, total).
- **Drawers** — collapsible panels, each backed by a file on disk,
  live-updating: Sheet (`sheet.md`), Canon (`surface.md`), Map
  (optional, when the story ships one). Rendered markdown.
- **Cast panel** — pinned placeholder in v1. Reserve the region and
  design the empty/loading state plus a card shape (name, one-line
  description, portrait slot) — portraits are a later asset-gen
  feature. No data source exists yet; design the socket, not the plug.
- **Resume banner** — a dismissible band above the stream showing where
  we are / what's wanted next, in the spirit of Baton's namesake baton
  handoff. Design it like a bookmark ribbon, not an alert. *Source note:*
  it reads a **player-safe `## Resume` recap from `surface.md`**, never
  the GM's baton in `state.md` — in a crawler or rules-game the baton is
  written to the GM and is full of spoilers. Uniform rule: the UI never
  derives anything from `state.md` or `gm/`.

## The core design constraint: per-story theming

**One story = one skin.** A story repo may ship `ui/theme.css`; the UI
must reskin *entirely* from CSS custom properties — color, type scale,
ornament, texture — with zero markup changes. Deliverable is therefore
a **token system + neutral default theme**, not a single look.

Acid test — the three example stories, three irreconcilable moods:

| story | kind | mood |
|---|---|---|
| **Greenmarch** | collaborative fantasy | walking-song pastoral: warm paper, green and ochre, serif, woodcut ornaments |
| **Neon Tithe** | cyberpunk crawler | wet asphalt and neon: dark, saturated accents, mono/grotesk, scanline energy |
| **Folio** | litRPG rules-game | drowned library-city: deep teals, drowned parchment, ledger-like sheet styling |

If the token system can carry all three without touching markup, it's
right. Shipping all three themes as proof would be ideal.

The **default theme** (no `theme.css` present) should be quiet,
bookish, and neutral — legible identity, no genre commitment.

## Components to spec

1. Design tokens (color, type, spacing, ornament slots) + light/dark
   for the default theme
2. Story stream: model prose block, player turn, scene break, streaming
   cursor state
3. Composer (idle, focused, model-is-writing/disabled)
4. Notary ticker line + public dice roll display
5. Drawer chrome: closed rail, open panel, live-update indicator
6. Cast panel: empty state + character card
7. Resume banner (player-safe recap from surface.md, not the baton)
8. Session states: connecting, watching-for-changes, model error

## Hard constraints

- **No build step.** Vanilla HTML/CSS/JS. No framework, no bundler.
- **Self-contained.** No CDNs, no webfonts fetched at runtime — system
  font stacks (or fonts a story theme embeds itself).
- **Light and dark** for the default theme; story themes may commit to
  one look.
- Wide content (maps, tables, sheets) scrolls in its own container.
- Must degrade to a phone screen: drawers become bottom sheets or
  tabs; cast panel collapses.

## Out of scope (v1)

Asset/portrait generation · choice/CYOA affordances · rendering
`state.md` or anything in `gm/` · authentication · multi-story
library view.
