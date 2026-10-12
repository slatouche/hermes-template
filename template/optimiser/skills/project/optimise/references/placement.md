# Where each thing belongs, and how it's written

The test for every line: **who needs it, and how often?** What every bot needs every session costs tokens on every
step of every bot, so only that goes where everything loads. Everything else goes where the bot that needs it
finds it when it needs it.

| Kind of content | Its place | Loaded |
|---|---|---|
| A rule every bot needs in every session (cards, boundaries, secrets, never `pkill -f`) | `workspace/AGENTS.md` (the team rules) | every session, every bot |
| One bot's job, judgement and boundaries: who it is, how it thinks, what it owns | that bot's `SOUL.md` (its role page `vault/system/roles/<role>.md` is the source) | every session, that bot |
| A procedure used sometimes (how to plan a build, take over a project, review a behavior) | a skill (`SKILL.md`, detail in `references/`) | when its task comes up |
| Longer explanation of a team rule (handoff fields, logging, memory habits) | `vault/system/team-habits.md` | when a rule points there |
| How the install works (services, jobs, ports, scripts) | `vault/system/overview.md` | on demand |
| A habit the owner approved after something went wrong | `vault/system/lessons.md` (one line, date, card) | session start |
| A durable fact about this project or the owner the bot learned (never a rule, progress or a to-do) | that bot's `MEMORY.md` / `USER.md` | every session, that bot |
| What a bot owns, agreed with the owner | `vault/team/<bot>.md` | on demand |
| A decision and why | `vault/log.md` (a `decision` line) or an ADR | on demand |
| Anything that can be done the same way every time | a script, with the prose shrunk to "run X" | never (it runs) |

## Signs something is in the wrong place
- A rule in `AGENTS.md` only one bot acts on → that bot's SOUL.
- A procedure (numbered steps, commands) in a SOUL or `AGENTS.md` → a skill, or a script if it has no judgement in it.
- The same point in two files → keep it in the one the table says; the other links to it or drops it.
- A rule in `MEMORY.md` (memory is for facts) → the SOUL or `AGENTS.md`, through a tidy proposal.
- Progress, a status or a to-do in a SOUL, `AGENTS.md` or memory → it's stale already; the board and `00-status.md` hold those.
- Detail nobody reads at the moment the rule applies (history, the case that caused it) → the lesson's card, the log, or nowhere.

## Writing it
- **Same shape everywhere:** every SOUL follows `vault/system/roles/_guide.md`'s section order; the same thing has the same name in every file (one term for "card", "build", "owner", "check").
- **Plain, positive, concrete:** the instruction first ("run X, then check Y"), the reason in a few words when it changes how the rule is applied, exact commands and paths.
- **One line per rule;** merge two lines that say one thing; cut words that change nothing.
- **Never lose meaning:** a rewrite keeps every rule's intent and outcome. Each old line maps to where its content now lives, or to why it can go (`meaning-check.py`).
- **Budgets:** the template's part of `AGENTS.md` 6.5 KB and of the Manager's SOUL 8.5 KB; a project's whole `AGENTS.md` under 8 KB, any SOUL under 10 KB. Tidy well inside them, not just under.
