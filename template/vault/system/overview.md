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
- Ports: the Hermes API server on {{API_PORT}} (localhost only); apps use {{APP_PORTS}}, laid out the same in every project: the app on the block's `01`, more services `02`-`09`, the design view on `51` and, for an app with a real back end, its design copy on `26` (localhost only, on a copy of the data). The real app has no toolbar.
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
- One shared board: `~/.hermes/kanban.db`. The dispatcher starts a worker per ready card, as the card's assignee. A second board, `rig`, holds the cards a check needs (nobody is subscribed, so they never reach the owner); `HERMES_KANBAN_BOARD=rig` picks it.
- Limits (default profile config): at most {{MAX_IN_PROGRESS}} cards running at once, 1 per bot; a card that fails twice is blocked (`failure_limit: 2`). Orchestrator: `manager`.
- **Builds** (`build.py`): every change to the app's code is a build: one branch (`build/<slug>`, `design/<stamp>`) and worktree (`~/wt/<slug>`), the cards that name it (`Build: <slug>`), each running only its own checks. When they're all done, the `build-tick` timer (systemd user timer, every 30 s; idle costs nothing) checks the whole build once (main merged in, the full suite, every card's checks; for an agreed design also the look check, `dv.py look`: each screen of the build against the agreed mockup, by the design view's headless browser), asks for the reviews it needs, each once for the whole build (a Designer look review only for screens that still differ, a Tester review only if a card wants it), merges into main, restarts the app's services and runs the live checks. A failure is one Engineer fix card; a failing live check puts main back; the third failure stops the build and goes to the Manager. State and history: `~/.hermes/builds/<slug>.json`; `build.py status`.
- After a crash or reboot, cards whose worker died go back to ready and re-run.

## Apps the owner uses
Anything the owner opens (an app, a page, an API) runs as a systemd user service in `~/.config/systemd/user/<name>.service` (`Restart=always`, enabled; it starts at boot without anyone logged in, because linger is on), on a port in the project's block, reachable from the LAN. The unit file is tracked in the memory repo. Restart it after a change: `systemctl --user restart <name>`.

## The design view (the owner's design surface)
**The design view** (`design-view.service`, `design-view.sh up`) on `<API port + 51>`: the owner's one design page. It serves the app's real front end (`workspace/frontend`, read from `main` on every request) with the **design layer** (`vault/design/layer/`: `ops.jsonl` edits, `history.jsonl` notes, `undone.jsonl` for redo, `options.json`, `data/` mock data, `agreed.md`, `archive/`) on top, under a toolbar: one note box for everything (changes, problems, questions, reactions, standing instructions, undo in words), Mark/Box/Arrow, instant Move/Text, options (live or side by side), one-click Undo/Redo, Agreed and the build's progress. Its eyes are its own **headless browser** (`design-view/mirror.js`, the project's Chromium), kept running beside it and current by itself: it shows the app as the owner has it (page, window size, scroll, option, the edits so far) and takes every picture (real screenshots) and every measurement, so the owner's page stays smooth; it shuts down after 20 idle minutes and starts again in a second when needed. A note runs as direct model calls (thinking off; a fixed-size knowledge pack, no Hermes session): first what the owner means (each spot they pointed at, a mark, a drawn box or where two marks meet, as a close-up with exactly what is drawn there; three looks at once, and when they don't agree the owner is asked which they mean), then a plan of parts; each change is measured, made from the numbers, checked against what was asked (style edits in place, so %, calc() and var() count; sizes by layout; whether the element is still seen; what is drawn at the spots before and after), repaired if it didn't take (the page names what holds it), then given a final look; options, screens, reviews and background parts run in parallel. Options never change the mockup: every choice is its own set, checked in the headless browser and repaired on its own. `/dv/dry-run` shows what a note would be taken to mean, changing nothing (`tests/understanding_check.py` scores it). An app with a back end runs a design copy (`design-api.service`, <API port + 26>) on a copy of its data (`~/design-data`); the owner's **↻ Data** button and every build going live refresh it from the real data (rsync; the real data is only read). **Agreed** means: this is the main app with the visible changes the owner wants; build it for real and make it work. It freezes the layer (the reference) and starts a build (`design-<stamp>`) that the Manager plans from the build sheet (`dv.py export`: what the owner asked, change by change in their words, and this round's build notes, which are part of the build): usually Engineer cards that fold the look in exactly and make everything it shows work, listing any state the design didn't show as `Look decisions:`. When its checks and the look check pass (and any review it needed), it goes live in the main app by itself, the layer is archived and the mockup starts from the new app (Unfreeze stops it). Anything about what the app does is only noted (no model call): a line on the running list `design/build-notes.md` (`build-notes.py`) with the owner's words, the screen and what the page saw, planned later with the owner by the Manager (the toolbar's 🔧 count lists the open ones; "urgent" also makes a Manager card); new behaviors are proposals that `behavior-check.py` checks first (safe, registers, sets up fast: about 2 s in the headless browser), then the Manager approves for fit (`dv.py approve`). Bots use `dv.py`. A new project starts from `~/.hermes/starter/frontend`.

## Cron jobs (default profile, no model tokens)
| Job | When | Does |
|---|---|---|
| `vault-sweep` | every 15 min | Logs each finished card (its summary's first line), regenerates `index.md`, commits leftover vault changes |
| `vault-lint` | 02:15 daily | Checks the vault; silent when clean, fails loudly on problems |
| `host-facts` | 03:05 daily | Rewrites [[system/host]] (`system/host.md`): OS, hardware, LAN address, port block, running app services, tools |
| `workspace-tidy` | hourly at :40 | Removes finished card worktrees and card branches already merged into main; never touches unmerged work |

**The Manager's jobs** (Manager profile; a script runs first and wakes the Manager only when it finds something, so quiet runs cost no tokens; scripts in `~/.hermes/profiles/manager/scripts/`):
| Job | When | Wakes the Manager when |
|---|---|---|
| `manager-watch` | every 15 minutes | wraps up a look whose design rounds stopped an hour ago (a Designer card, no model call); a new finding: a question a bot put to the owner (screened: is it really theirs?), board diagnostics, a card blocked or in triage over a day, sent back twice, over its runtime, ready with nobody on it (owner items never count: they wait without nagging); a handoff with no card id; memory over 90%, `AGENTS.md` over 8 KB, a SOUL over 10 KB, lessons over 40, lint problems, an import left 3 days, a stale unmerged branch. Each finding is raised once, then again after a day if still open |

The Manager's chat messages carry a **state pack** (`state-pack.py`, added by the Manager's `state-pack` plugin when it changed: status fields, board, owner queue, builds, last log lines), so status questions need no reading steps.

**The Optimiser's job** (Optimiser profile, hired in every project; script in `~/.hermes/profiles/optimiser/scripts/`, kit in `~/.hermes/roles/optimiser/`):
| Job | When | Wakes the Optimiser when |
|---|---|---|
| `optimiser-review` | 02:40 daily | since its last run (`optimiser-gate.py` reads the board, every bot's log, the owner's chat times and the builds): an outlier card, a slow tool call, a big context, a card shape repeated 3+ times, building by a role that doesn't build, slow replies to the owner, a send-back or block, a failed build, a bot-written skill, memory over 85%, a model change, or 10+ cards done. It runs the `optimise` skill: measured, tested proposals in `system/changes/` and one card for the Manager to screen them. Also every night a **tidy** of one slice in rotation (the team rules, one bot's SOUL source, skills and memory, the vault's system pages; skipped when nothing in it changed): the same rules said once, in the right place, with a meaning map for every line (`tidy.py`); the Manager applies one that passes `tidy.py check`, except one changing an instruction file (team rules, a SOUL): Hermes lets those change only with a person there, so that one waits for the owner's yes in a chat (rollback: `tidy.py rollback`). It changes nothing live |

## Every loop has a stop
| Loop | Stop |
|---|---|
| A worker crashes, times out or fails to spawn | blocked after 2 (`kanban.failure_limit`) |
| A worker ends without a board call | blocked after 3 in a row (Hermes) |
| One worker's runtime | killed and requeued at the card's `max_runtime_seconds` |
| Worker turns | warning at 80%, stop at the role's `max_turns` |
| The same check failing | three tries, then revert and block (AGENTS.md) |
| A build failing its checks | one fix card per failure; the third stops the build and goes to the Manager (`build.py`) |
| The same owner question re-blocked | to triage after 2 (Hermes) |
| Goal-mode card | 6 turns |
| Sub-agents | 3 at once, 60 iterations each |
| A stuck card | `manager-watch` raises it within 2 hours; the Manager never loops a card a fourth time |

## Scripts (`~/.hermes/scripts/`)
`design-view.py` and `design-view.sh` (the design view), `dv.py` (bots' handle on it: map, apply, undo, propose, approve, export, landed), `build.py` (builds: start, ready, status, checks, tick, abort), `behavior-check.py` (a proposed behavior's safety and speed, by script), `state-pack.py` (the project's state in a few hundred words), `tidy.py` (the nightly tidy: slices, staging, the meaning map's check, apply, rollback), `vault-log.sh` (append to `log.md`), `vault-commit.sh` (checkpoint named files), `vault-index.py`, `ui-check.sh` (real-input checks: a real click or real typing on a control, for testers), `board-now.py` (every running card, its time and last step; no model), `vault-sweep.sh` (with `card-log.py`: a log line per finished card), `vault-lint.py`, `vault-lint-job.sh`, `workspace-tidy.sh`, `hire.sh`, `skill-check.py` (checks a skill folder for planted instructions before a bot gets it; `hire.sh` runs it), `raw-stamp.py` (fingerprints a raw source), `run-eval.sh` (a bot's fixed eval, before and after a change), `vault-changes.sh` (what changed in the vault since you last looked; the `/vault-changes` quick command in a Manager chat), `import-survey.py` (a zero-token survey of `workspace/`: shape, how it runs, other AI tools' files, secret risks; writes `raw/predecessor/inventory.md`). Cron scripts must live here.

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

## Cards resume their sessions
Hermes runs every card as a fresh worker. The gateway launches workers through `$HERMES_BIN` = `~/.hermes/scripts/hermes-worker.py` (a systemd drop-in, `hermes-gateway.service.d/topic-sessions.conf`), which adds `chat --resume` so the bot carries on with what it knows: a card with `Session: <topic>` resumes that bot's last session for the topic; any other card resumes the bot's own last session on that card when it comes back to it (sent back, unblocked, reviewed, or out of turns). It follows Hermes's compression chain and waits for the card's previous worker to exit first. Per bot: `<profile>/topic-sessions.json` (topic or `card:<id>` -> session), `<profile>/topic-locks/` (one live worker per topic), `<profile>/logs/topic-sessions.log`; a resume is also a comment on the card. Fresh instead when: a card's first run, `Session: none` or `Session: new <topic>`, the card's last run by that bot crashed or failed (running out of turns isn't a failure), the session is gone, idle over 3 days or past 40 cards, or the topic is held by a live worker on another card. `hermes-worker.py --topics [list|reset <topic>]` with `HERMES_HOME` set to the bot's profile. The dispatcher checks for ready cards every 10 s; a resumed session idle over an hour is condensed first.
