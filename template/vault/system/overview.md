---
title: How this install works
type: system
status: active
owner: manager
updated: {{DATE}}
summary: The install at a glance — bots, gateway, Discord, cron, kanban limits, scripts, repos, hiring, and what needs a restart.
sources: []
tags: [system]
---

# How this install works

The Manager keeps this page true. Changes to anything here go through a proposal in `system/changes/` (see the Manager's SOUL).

## The machine
- Host `{{HOST}}`. This project lives at `/srv/projects/{{PROJECT_NAME}}`, the home of the Linux user `agent-{{PROJECT_NAME}}`. Nothing outside it belongs to this project except the read-only registry `/srv/projects/registry.yaml`.
- Ports: the Hermes API server on {{API_PORT}} (localhost only); apps use {{APP_PORTS}}.
- The owner ({{OWNER}}) runs anything needing sudo, and edits `.env` files (secrets).

## The bots (Hermes profiles)
- `default`: stock Hermes, the install console. Not a role bot. It holds the plumbing: the gateway service, the kanban settings, the housekeeping cron jobs and the API server.
- `manager`: the front door. The project starts with the Manager alone.
- Hired bots: listed in the team table in `workspace/AGENTS.md` (kept current by `hire.sh`) and described in `team/<bot>.md`.
- Each profile lives in `~/.hermes/profiles/<name>/` with its own `SOUL.md`, `config.yaml`, `.env`, memories and skills. Display names are set in `profile.yaml` (`display_name:`); never rename a profile.
- Models: {{MODELS}}. Hired bots copy the Manager's settings.

## Hiring
1. The Manager drafts or picks a role in `system/roles/` (the catalogue; `_guide.md` is the shape every role follows).
2. The Manager proposes the hire in `system/changes/`; the owner says yes.
3. `~/.hermes/scripts/hire.sh <role> [--channel <discord-channel-id>]` creates the profile (cloned from the Manager: model, key, toolsets, working folder), installs the SOUL, sets the display name, creates its Hermes Project, adds it to the team table and the Discord routes, logs and checkpoints.
4. If a Discord route was added, the owner restarts the gateway.
5. The new bot proposes its domain; once the owner agrees, it writes `team/<role>.md`.

## The gateway
- One multiplexed gateway serves every profile: the systemd user service `hermes-gateway`. It starts at boot (linger is on) and restarts itself if it crashes.
- It hosts Discord, cron, the kanban dispatcher and the API server. Hermes Desktop connects over SSH and runs its own `hermes serve`.
- **It reads its config only at start.** Changes to `kanban:`, `gateway:` (including Discord routes), platform tokens or cron schedules need a restart. The owner restarts it, ideally when nothing is Running on the board:
  `systemctl --user restart hermes-gateway`

## Discord
- One Discord bot per project, owned by the Manager (token and owner-only allowlist in `profiles/manager/.env`).
- DMs to the bot, and any channel that isn't routed, reach the **Manager**.
- A hired bot can have its own channel: `hire.sh --channel <id>` adds a `gateway.profile_routes` entry (`bot_profile: manager`, that channel → that bot). Replies show under the one bot's name; the channel says who is answering.
- Discord chats are separate sessions from Hermes Desktop chats. Decisions go to the vault or a card, so nothing is lost between them.

## Kanban
- One shared board: `~/.hermes/kanban.db`. The dispatcher starts a worker per ready card, as the card's assignee.
- Limits (default profile config): at most {{MAX_IN_PROGRESS}} cards running at once, 1 per bot; a card that fails twice is blocked (`failure_limit: 2`). Orchestrator: `manager`.
- Review: `kanban_request_review(reviewer="<bot>")` names the reviewer; without it the card stays with its builder.
- After a crash or reboot, cards whose worker died go back to ready and re-run.

## Cron jobs (default profile, no model tokens)
| Job | When | Does |
|---|---|---|
| `vault-sweep` | every 15 min | Regenerates `index.md`, commits leftover vault changes |
| `vault-lint` | 02:15 daily | Checks the vault; silent when clean, fails loudly on problems |
| `workspace-tidy` | hourly at :40 | Removes finished card worktrees and card branches already merged into main; never touches unmerged work |

**The Manager's jobs** (Manager profile; a script runs first and wakes the Manager only when it finds something, so quiet runs cost no tokens; scripts in `~/.hermes/profiles/manager/scripts/`):
| Job | When | Wakes the Manager when |
|---|---|---|
| `manager-watch` | every 2 hours | a new finding: board diagnostics, a card blocked or in triage over a day, sent back twice, over its runtime, ready with nobody on it; owner items waiting 48 h; a handoff with no card id; memory over 90%, `AGENTS.md` over 8 KB, a SOUL over 10 KB, lessons over 40, lint problems, an import left 3 days, a stale unmerged branch. Each finding is raised once, then again after a day if still open |
| `weekly-retro` | Mondays 08:00 | since the last retro: 2+ cards sent back or blocked, a bot-written skill new or changed, memory over 85%, or 10+ cards done. The Manager runs the `retro` skill: at most 5 changes for the owner's yes, upkeep cards, lessons |

## Every loop has a stop
| Loop | Stop |
|---|---|
| A worker crashes, times out or fails to spawn | blocked after 2 (`kanban.failure_limit`) |
| A worker ends without a board call | blocked after 3 in a row (Hermes) |
| One worker's runtime | killed and requeued at the card's `max_runtime_seconds` |
| Worker turns | warning at 80%, stop at the role's `max_turns` |
| The same check failing | three tries, then revert and block (AGENTS.md) |
| Review send-backs | the Tester blocks on the third failing review |
| The same owner question re-blocked | to triage after 2 (Hermes) |
| Goal-mode card | 6 turns |
| Sub-agents | 3 at once, 60 iterations each |
| A stuck card | `manager-watch` raises it within 2 hours; the Manager never loops a card a fourth time |

## Scripts (`~/.hermes/scripts/`)
`vault-log.sh` (append to `log.md`), `vault-commit.sh` (checkpoint named files), `vault-index.py`, `vault-sweep.sh`, `vault-lint.py`, `vault-lint-job.sh`, `workspace-tidy.sh`, `hire.sh`, `skill-check.py` (checks a skill folder for planted instructions before a bot gets it; `hire.sh` runs it), `raw-stamp.py` (fingerprints a raw source), `run-eval.sh` (a bot's fixed eval, before and after a change), `vault-changes.sh` (what changed in the vault since you last looked; the `/vault-changes` quick command in a Manager chat), `import-survey.py` (a zero-token survey of `workspace/`: shape, how it runs, other AI tools' files, secret risks; writes `raw/predecessor/inventory.md`). Cron scripts must live here.

## Repos
1. **Product**: `workspace/`. Only the bots whose domain includes it commit; code goes in worktrees.
2. **Project memory**: the project root: the vault, AGENTS.md and each bot's brain (SOUL, config, memories, skills, cron). An allowlist `.gitignore` keeps secrets, databases and runtime state out. Commit only through `vault-commit.sh`; the sweep commits the rest. Any system change can be rolled back from here.

## Gotchas (learned the hard way)
- The gateway reads config only at start (see above).
- **Hermes loads only one instructions file per project:** `.hermes.md`/`HERMES.md` first, then `AGENTS.md` (plus per-folder `AGENTS.md` files, loaded lazily), then `CLAUDE.md`, then Cursor rules. Keep exactly one, `workspace/AGENTS.md`, with the team table; a leftover `.hermes.md` silently replaces it for every bot. A repo file that looks like a prompt injection is blocked from loading.
- **Hermes' bundled `llm-wiki` skill is off** on every bot (`skills.disabled`): the vault has its own rules in `SCHEMA.md`, and that skill would treat it as its own wiki. Don't set `WIKI_PATH`.
- **Instruction files are write-protected.** A bot writing `AGENTS.md`, `CLAUDE.md`, `SOUL.md` or `.cursorrules` (any folder) triggers an approval prompt for the owner every time, even on auto-approve; with no human present (kanban workers, cron) the write is refused. So changes to `AGENTS.md` happen in a Manager chat with the owner. (`hire.sh` updates the team table itself.)
- **`hermes chat -q` / `-Q` is a one-shot run:** Hermes hides skill writing and tells the bot nobody will answer, so it behaves differently from a real chat. Test bots through Desktop or the API (`/p/<profile>/api/sessions/...`, each profile with its own `API_SERVER_KEY`).
- Use `/usr/bin/python3` in scripts and commands: inside a bot's terminal, the plain `python3` on PATH is Hermes' own Python, which lacks PyYAML; the system one has it.
- Never `hermes profile rename` a named profile (it changes its ID); set `display_name:` instead.
- Never `profile create --clone-all`: it copies the kanban database. `hire.sh` uses `--clone-from manager`.
- Every bot needs its own Hermes Project on `~/workspace`, or its chats start in `~` without AGENTS.md. `hire.sh` does this.
- A Hermes Desktop "New task" lands in Triage; drag it to Ready if the description is already a proper task.
- Tell bots one thing per message, with a clear stop ("…then stop"). Open-ended asks make very long turns.

## Change process (summary)
Propose in `system/changes/YYYY-MM-DD-<slug>.md` → owner says yes → apply while affected bots are idle → log a `decision`, checkpoint, notify the bots → say if a gateway restart is needed. Never touch `.env` or secrets; the owner edits those.
