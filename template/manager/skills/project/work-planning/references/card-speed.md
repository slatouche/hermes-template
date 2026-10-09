# Where a card's time goes, and how to measure it

## The cost model
Wall clock = dispatcher tick (~10 s) + process start (~3 s) + **model turns** + **tool time**. Turns dominate: every tool call costs one more turn (5-20 s each; the first call of a card on an existing session can be ~25 s), so **the number of steps is the cost**. A round's edits and its check in one script beats four separate writes, and a small session beats a big one.

## Reading the bot's own log (the only real breakdown)
`~/.hermes/profiles/<bot>/logs/agent.log` — filter, never read whole:

- `grep "API call #" …` → `in= out= latency= cache=` per turn. `in=` is the whole session's token count: 120k+ means the session is the problem, and a turn with no `cache=` reading is a cold read (a new card re-sending the session).
- `grep "tool_executor: tool" …` → each tool with its own duration: `tool patch completed (22.32s, 891 chars)`.
- `grep "conversation turn:" …` → `session=… history=N model=…`; a big `history` is a long-lived session being dragged around.
- `grep "Vision auto-detect" …` → `agent.auxiliary_client: Vision auto-detect: using main provider <x> (<model>)`: the look is served by the main model, so an image is slow and, on a vision-capable main model, sticky in history.
- `awk '$0>="<start>" && $0<="<end>"' <log> | grep -v check_fn` → what, if anything, happened during a slow tool call. No lines between two timestamps means the tool blocked silently.

## Measure before blaming
Reproduce the same operation in your own session and time it (the identical patch, the same curl, the same file). A 20 s+ tool duration you cannot reproduce in ~0.1 s is that profile's environment — a post-write check, contention, a stale server — not the tool. Report it as "not reproduced" and watch the next run rather than waking a bot to chase a maybe.

## The shape of a measured round
A four-edit design round came to 164 s: **67 s** in nine model turns (24.8 s of it the cold first call on a 122k-token session), **45 s** in two 22 s patches, **16 s** in two terminal checks, **30 s** in a single `vision_analyze`, 5 s for the two fast edits and the handoff. Fixes worth making, in order of size: a smaller session (a new area gets a new topic), fewer separate writes (one script per round), and no look where a number answers. The lesson is the shape, not the digits.

## Sizing a session (the knobs, and what they must not cut)
Three settings in `.hermes/profiles/<bot>/config.yaml` decide how much a bot drags into its next card:
- `prompt_caching.cache_ttl` — how long the cached session stays usable. The default is minutes, so cards on one topic that arrive minutes apart re-read the whole session cold (~25 s first turn). `1h` for a long session with pauses between turns. It only applies to Claude models; other providers (DeepSeek) cache on their own, so there the idle tidy below is what keeps the next card fast.
- `compression.threshold_tokens` — where the session summarises itself. Summarising is lossy, so size it to the **largest unit of work the bot must hold at once**, not to average speed: a design round adds roughly 5-9k tokens, so ~120k holds a whole page's rounds (15-20) and still catches a runaway. A cap that cuts a page-wide design mid-flight costs more than it saves.
- `compression.idle_compact_after_seconds` — tidy when work stops so the next card starts small *and* still cached; set it just under the cache TTL (45 min under an hour).
Back the file up first (`config.yaml.bak-<stamp>`), change only those keys, and `diff` backup against result as the check (no YAML parser is available in the project's python, so the diff is the proof). A config change reaches the bot's next session, never the running one.

## One command still narrates itself
The round tool doing the whole round in one call means the *bot* cannot narrate its edits, so the tool writes its own rows into the card's log (`~/.hermes/kanban/logs/<card>.log`): the same `┊ <label>   <n>s` rows the chip reads, **with a duration** — the reader (`feedback-inbox.round_step`) takes the last *finished* row, so a row without one is ignored and an older row wins. A tool that lands several edits in turn therefore appends a row per edit and the owner watches each arrive. `board-now.py` reads the same log.
