# Examples — three starters, one per kind

Each example is a ready-to-inhabit *surface*: setting, tone, and a
staged opening. None of them ship hidden world-truth — that's not
stinginess, it's the point. In a crawler or rules-game, your GM writes
`gm/` **alone** after you've both read the surface, commits, and hands
you the hash. A pre-written secret in a public repo is a spoiled game;
the ritual of sealing your own is where the trust comes from.

| example | kind | it teaches |
|---|---|---|
| `greenmarch/` | collaborative | shared canon + a `register.md` in action |
| `neon-tithe/` | story-crawler | hidden GM map, branching jobs, honor-system `gm/` |
| `folio/` | rules-game | the kernel ritual: precommit, publish the hash, play fair |

## To start one

```
cp -r examples/<name> ~/stories/<name>
cd ~/stories/<name> && git init -b main && git add -A && git commit -m "found"
```

Then read `state.md` — its baton tells you (and your GM) exactly what
to do next. Tweak the surface freely before the first commit: it's
yours now.
