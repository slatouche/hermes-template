---
title: "Team habits: direct work, memory, and learning"
type: system
status: active
owner: manager
updated: {{DATE}}
summary: "The longer form of two team-guide (AGENTS.md) sections, kept here so the guide stays under 8 KB: the owner talking to a specialist, and memory and learning."
tags: [system, habits]
---
# Team habits

The team guide every bot loads each session is kept short on purpose (under about 8 KB: it is in every session's context). The wordier parts live here; the guide links to this page.

## Direct work (the owner talks to a specialist)
- **Tiny** (a question, a quick look, no files): just answer.
- **Build work:** a card assigned to yourself; a worker does it, and the owner is told when it's done.
- **Live iteration with the owner** (try, look, adjust): the card with `initial_status="blocked"` (a `ready` self-card starts a second worker), work in the chat, finish with `kanban_complete` and a `Verified:` line. The summary becomes the log line.

## Memory and learning
- `MEMORY.md` holds durable facts about this project and its owner — never progress, to-dos or secrets; when full, merge in one go and keep what the owner said. Read `vault/system/lessons.md` at session start: team habits the owner approved.
- Look it up before asking: `session_search`, the vault, the repo. What other bots need goes in the vault, not only your memory.

## Card handoff (every kanban completion)
`kanban_complete(summary=…, metadata=…)`:
- `summary`: at most 5 lines. First `Verified: <command> → <result>` per check; then what was done and what's next.
- `metadata`: `changed_files`, `decisions`, `tests_run`, `attempts`, `checks_failed`, `open_questions`, `next`.
- The card's log line and vault checkpoint are automatic (the sweep logs the summary's first line): don't spend steps on them.

## Logging and checkpoints
- Finished cards log themselves. Decisions outside a card: `~/.hermes/scripts/vault-log.sh <bot> <kind> "<text>" [link]`.
- **Checkpoint** with `~/.hermes/scripts/vault-commit.sh <bot> "<msg>" <files…>` only when another bot needs it now; the sweep commits every 15 min. No raw git in the memory repo; `index.md` is generated, so give pages a `summary:`.

## Asking the owner
Only what's theirs: scope or taste, money or risk, something only a person can do, or a gap the vault doesn't settle. Technical and testing calls are the team's; a clash inside your card goes to the Manager. Never wait in a loop or ask in a chat nobody reads.

## Steps
Each step waits on the model (5-20 s). Three or more reads or checks with logic between them go in one `execute_code`.
