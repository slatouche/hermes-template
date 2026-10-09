# Kanban CLI shapes, and who a card can notify

## Boards
- `hermes kanban boards` — slug, name, counts. `boards create <slug> --name "<name>"`, `boards switch <slug>`, `boards rm <slug>`.
- Pick a board for one command with the env var: `HERMES_KANBAN_BOARD=<slug> hermes kanban …` (a `--board` flag in that position is rejected).
- Each board is its own DB, workspaces and dispatcher loop — cards there cannot collide with the project board, which is what makes a throwaway board safe.
- **A subprocess inherits its board from the environment, so a tool that closes its own card must be told the board.** A `delegate_task` child, or any worker with no `HERMES_KANBAN_BOARD`, runs `hermes kanban …` against the wrong board: `complete <id>` then fails with `unknown id or terminal state` although the card exists, and the worker closes it by hand instead. Pass the board in and set it on the child's environment; never inherit it.

## Creating, closing, reading
- `hermes kanban create "<title>" --assignee <bot> [--body …] [--initial-status blocked|running] [--json]` — **the title is positional**; `--title` is rejected.
- `hermes kanban complete <id> --force --result "<one line>"` closes a card a worker still holds; without `--force` it refuses.
- `hermes kanban show <id> --json` → `task` (with `result`), `latest_summary` (the handoff, including any question the worker left), `comments`, `events`, `runs`.
- `hermes kanban list --json` returns a flat array (no `--limit`) whose rows carry `id`; it is refused inside a dispatched worker's shell, so `owner-queue.py` / `board-now.py` print nothing there.
- The CLI's `--json` payloads do **not** share the kanban *tool*'s key names — the tool answers `task_id`, a `create … --json` payload does not. Read the id from the payload you were given (or from `list --json`) instead of indexing a key you assumed; a wrong key is a `KeyError` that costs a turn and looks like a failed create.
- `hermes kanban edit` cannot set `max_runtime_seconds`; set it at create.
- A dispatch notice saying `timed out (max_runtime=0s)` is misleading: the real cause is the run's `error` field, usually `Iteration budget exhausted (60/60)` — the card burned steps, not clock.

## Who gets told (the notification path)
- `hermes kanban notify-list` lists every subscription as `<card> <platform>:<chat> (since event N) owner=<profile>`; `notify-list <id>` shows one card's subscribers. **`(no subscriptions)` is the ground truth: nothing about that card can reach a chat.**
- A card created from a chat session is subscribed to that chat, so blocking it rings the owner with `Task blocked — needs your input`. A check that needs a card to exercise blocked/review/answer states therefore creates it on a separate board — a card created there and completed shows no subscriptions at all, and `--initial-status blocked` fires no block event either.
- `notify-unsubscribe <id> --platform <p> --chat-id <c>` exists but needs the chat coordinates; not creating the card on the owner's board is the better fix.
