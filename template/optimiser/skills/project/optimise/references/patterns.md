# Patterns worth fixing, how to spot them, and the usual fix

Each comes from a real case in a project built from this template. The numbers are what made it worth fixing.

## The same overhead on every card
- **Spot:** a card shape that repeats per piece of work (`Land <x> on main`, `Review <x>`, `Preview <x>`) with similar duration each time; the pack's "repeated shapes".
- **Case:** landing (merge, full suite, restart) was a 7-13 min bot card after every Engineer card, and a Tester review per card. Fixed by `build.py`: cards share one branch and run only their own checks; the whole build is checked, reviewed and landed once, by script.
- **Fix:** move the step to the end of the batch, or into a script; the per-card instruction shrinks.

## A deterministic step done by a model
- **Spot:** a card or chat turn whose steps are all commands with no judgement between them (merge, run tests, restart, copy, curl a status, move a file).
- **Case:** "Designer: preview the build" ran four commands as an agent card (2-5 min). Removed: the design view follows the build itself.
- **Fix:** a script (with tests), called by whatever triggers it; the bot's role text names the script instead of the steps.

## Reading at the start of every turn
- **Spot:** the first 2-5 tool calls of most turns are the same reads (board, status page, log tail); `tools over all turns` dominated by `terminal`/`read_file`.
- **Case:** the Manager's chat replies took 2 min median (p90 6 min); ~4 steps each, most of them reading state. Fixed with the state pack (`state-pack.py`, added to each chat message by the Manager's `state-pack` plugin when it changed).
- **Fix:** hand the bot what it needs (a pack, the card carrying the facts), and say in its instructions to answer from it.

## The wrong role doing the work
- **Spot:** the pack's "wrong role" list: a Tester card titled Build/Add/Fix/Land, a Manager card that edits code, a Designer card that wires an API, the owner asked a technical question.
- **Fix:** route by domain (`work-planning` step 0), propose a hire if no bot fits, or a check in the card-cutting step.

## Big sessions and slow single steps
- **Spot:** `in=` over ~120k on most turns, a first turn with no `cache=` (cold), a tool over 20 s (`tool X completed (22.3s`), a `vision_analyze` where a DOM number answers.
- **Fix:** compaction thresholds and idle tidy (`references/card-speed.md`), a new topic for a new area, numbers before pictures. Measure the same operation yourself first: 0.1 s for you and 22 s in the card means the environment, not the tool.

## Loops
- **Spot:** send-backs, a build failing more than once (`~/.hermes/builds/*.json` history), the same check failing, a card re-run after a crash.
- **Fix:** the check is wrong (fix the check), the card is too big (re-slice rule), or the instruction is unclear (rewrite it as a command); never a fourth try at the same thing.

## Instructions not followed, or followed anyway
- **Spot:** the owner correcting the same thing twice; a rule in a SOUL the bot broke in the logs; a rule the bot follows with or without it (try removing it on a copy and re-running the eval).
- **Fix:** a check or a script for the first; delete the second. Shorter context is faster and more obeyed.

## Rules creeping toward a limit
- **Spot:** the pack's "loaded every session and near its limit" list: `AGENTS.md` (8 KB), a SOUL (10 KB). Each fix adds a line, each hire a table row, and the project section grows, until a file is over and gets trimmed in a hurry.
- **Case:** TCG Proxy's `AGENTS.md` reached 8,410 bytes after one hire; the template's own part was 7.7 KB, leaving no room for the project's section and rows. Fixed by budgets: the template's part at most 6.5 KB (AGENTS.md) and 8.5 KB (the Manager's SOUL), held by `tests/test_budgets.py`; `hire.sh` refuses a row that would go over 8 KB.
- **Fix:** propose what to move (detail to `vault/system/team-habits.md`, a procedure to the skill that runs it), what to merge (two lines saying one thing) and what to delete (a rule the model follows anyway, checked with the bot's eval before and after). Never cut a rule's meaning to save bytes; say for each line where its content now lives.
