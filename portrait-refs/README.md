# Portrait references (demo)

Reference images generated while researching image-gen options for Baton's
(v1-out-of-scope) portrait feature. Same three player-safe *Drowned Stacks*
subjects — a house-style establishing shot, a character portrait, and a crew
shot — rendered through different free/keyed APIs to compare on-register output.

| zip | engine | model | notes |
|---|---|---|---|
| `drowned-stacks-refs.zip` | Pollinations (no key) | Flux | free, frictionless; good mood, Kest face melts, crew came out 4-not-3 |
| `drowned-stacks-refs-google.zip` | Google Gemini | gemini-3.1-flash-lite-image ("Nano Banana 2 lite") | **best of the set** — clean faces/hands, correct 3-crew count, in-world signage, real depth |

Leonardo (the fantasy-reputation pick) was set up and its generator validated
against the live API, but the account had **no API tokens** (web-subscription
tokens don't fund the API), so no Leonardo set was produced. `gen_leonardo`
logic is ready if an API plan is added.

Each zip carries its own README (prompts, seeds/aspect ratios, style spine) and
the generator script. No `[SEALED]` story content is encoded — appearances the
player has already seen only.
