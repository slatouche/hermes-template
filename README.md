# Hermes project template

Stand up a new Hermes project on the P330 with one command. Each project gets its own Linux user, its own Hermes install, a vault (knowledge base), two git repos, housekeeping jobs, and **one bot: the Manager**. You talk to the Manager (on Discord or in Hermes Desktop). It interviews you, sizes the process to the project, and hires the rest of the team as needed, with your OK.

## What you need for each new project
1. **A name.** Lowercase letters, digits and `-`, for example `story-maker`. It becomes the folder `/srv/projects/<name>`, the Linux user `agent-<name>` and the Discord bot's context.
2. **An OpenCode Go API key** for the project. Create a service account in the OpenCode console (Inference only), set a budget on it (for example $10/month), and copy the key.
3. **A Discord bot** (optional, can be added later):
   1. [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**, named after the project.
   2. **Bot** page → **Reset Token** → copy the token. Turn on **Message Content Intent**.
   3. **OAuth2 → URL Generator**: scopes `bot` and `applications.commands`; permissions View Channels, Send Messages, Send Messages in Threads, Read Message History, Attach Files, Add Reactions. Open the URL and add the bot to your private server.
   4. Discord **Settings → Advanced → Developer Mode** on, then right-click yourself → **Copy User ID**.
   5. Create a channel for the project (for example `#story-maker`). Later, one channel per hired bot if you want to talk to them directly.

## Create a project
One command on the server, as your admin user (the one with sudo):
```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/slatouche/hermes-template/main/install.sh)"
```
It puts the template in `/opt/hermes-template` (owned by root; re-running updates it) and asks for:
1. the project name;
2. an existing project to import, or Enter to start from scratch;
3. the OpenCode key (hidden; skipped if `PROVIDER_KEY_FILE` is set in `/etc/hermes/host.conf`);
4. a Discord bot token (Enter skips; add it later).

Later projects: `sudo bash /opt/hermes-template/new-project.sh` (or the same one-liner, which also updates the template). Don't pipe it into `sudo bash`: the questions can't read your keyboard that way. Options for scripts: `<name> --import <source> --notes <folder> --key-file <file> --no-discord`. Host settings (owner name, subnets, a key file) go in `/etc/hermes/host.conf`, which overrides `host.conf` and survives updates. Allow 5–10 minutes; the first run on a fresh server also installs Ubuntu packages. It's safe to re-run if something fails part-way.

What it does:
| Part | As | Steps |
|---|---|---|
| 1 | root | installs missing Ubuntu packages (git, Python YAML, ripgrep, ffmpeg, the headless browser's libraries); registry entry (next number → ports `1NN00-1NN99`); user `agent-<name>` with home `/srv/projects/<name>`; you added to its group; your SSH keys copied (for Hermes Desktop); linger; firewall rules for the app ports |
| 2 | `agent-<name>` | installs Hermes; keys; default profile config (model, kanban limits, API server); vault from the template; scripts; `workspace/` repo; the **Manager** profile (SOUL, display name, Hermes Project, Discord); kanban board; `vault-sweep` and `vault-lint` jobs; the project memory repo; the gateway service |

It's safe to re-run if something fails part-way: finished steps are skipped.

At the end it prints an SSH config block. Add it to `~/.ssh/config` on your PC, then:
- **Hermes Desktop:** add an SSH connection to `p330-<name>` and open the Manager.
- **Discord:** DM the bot or post in the project channel. The Manager sees a new project (`phase: setup`) and starts the intake interview.

## Adopt an existing project
A project built elsewhere (Claude Code, Codex, Cursor, another Hermes, by hand) can come in two ways.

**At creation:** answer the "Import from" question with a git URL, or a repo folder, plain folder or `.bundle` file on the server. Or pass it:
```bash
sudo bash /opt/hermes-template/new-project.sh tcg-proxy --import https://github.com/<you>/<repo>.git
```

**Later, through the drop folder:** every project has `~/import/`. Copy the project in with the project's own SSH login (so the files belong to the project), then tell the Manager:
```bash
scp -r "C:/Users/you/Projects/my-project" p330-<name>:import/
```
> "Take over the project in ~/import/my-project."

Or just give the Manager a git URL. The Manager runs `~/.hermes/scripts/import-project.sh` itself.

What happens:
- Only committed files come in, with full history; for a plain folder, its files become the first commit (secrets, caches and venvs skipped). What git left behind (data, caches, local settings) is listed in `vault/raw/predecessor/not-imported.md` so nothing is lost silently.
- A private GitHub repo: at creation in the terminal it asks for a read-only fine-grained token; in a chat, copy the folder into `~/import/` instead (bots never take tokens in chat).
- `--notes <folder>` (or a notes folder in `~/import/`) brings an old bot's memory, owner notes and skills as evidence; anything secret-looking is skipped.
- The project goes to `phase: onboarding`. A zero-token survey writes `vault/raw/predecessor/inventory.md` (shape, how it runs and tests, every file another AI tool left, tracked secrets) and snapshots those tool files.

When you talk to the Manager it takes the project over (`project-takeover` skill):
1. surveys the repo and runs its tests for a baseline;
2. keeps the know-how: each old rule, note, command or skill goes to the right place (the new `AGENTS.md`, a vault page, the owner profile, or a Hermes skill for a future hire), or is dropped with a reason;
3. asks you, one question at a time, only what the repo can't answer;
4. proposes one takeover change: a single instructions file (`AGENTS.md`, with the team table), the removal of other tools' files in one commit, the team, the first cards, and what happens to the drop folder;
5. applies it after your yes (Hermes shows an approval prompt for the `AGENTS.md` write), re-runs the tests (reverting if anything got worse), moves any data you want kept to `~/data/`, empties the drop folder, and moves on to normal work.

## How it grows
- The Manager proposes each hire in `vault/system/changes/`. The catalogue in `vault/system/roles/` has an Architect, Engineer, Designer, Tester and Researcher (hire the Researcher with `--skill ~/vault/system/skills/app-teardown` to study other apps). For anything else (a Writer, say) the Manager drafts a role from `_guide.md`.
- After you say yes, the Manager runs `~/.hermes/scripts/hire.sh <role> [--channel <id>]`. For a bot with its own Discord channel, create the channel, give the Manager its ID, and restart the gateway afterwards:
  ```bash
  ssh p330-<name> "systemctl --user restart hermes-gateway"
  ```
- All changes to how the team works (SOULs, config, jobs) go through the same propose → approve → apply loop. The Manager never touches `.env`, sudo or the gateway.
- `vault/system/overview.md` in each project explains how its install works.

## Keeping an eye on it
- **`/vault-changes`** in a Manager chat: what the bots changed in the vault since you last looked (page by page, no model call). Anything wrong rolls back from git.
- **`~/.hermes/scripts/run-eval.sh <bot>`:** a bot's fixed eval (`vault/system/evals/<bot>.md`), run before and after changing its SOUL or skills.
- Skills kept from an imported project are rewritten and checked (`skill-check.py`) before any bot gets them; `hire.sh` refuses one that fails.

## Working with your team
- **Talk to the Manager** for anything: ideas, status ("where are we?"), "build it". You can also chat with a specialist directly (the Designer for design rounds); what's decided lands on the board and in the vault.
- **What needs you** is a card blocked for you, and it waits as long as it takes. `/queue` in a Manager chat lists them; the Manager screens every new one within 15 minutes and answers the ones that aren't really yours.
- **Mark it up:** every app the team serves has a review link with the Mark toolbar (click an element or drag an area, type, Save). Notes are drafts until you press **Send**, which hands that link's notes to the team as one round; each note records where it was left, what was inside the box and a cropped picture.
- **Design:** the **mockup** is a copy of the app (your real data is never touched) with the Designer's looks on it; the badge switches looks. **Demo 1 and 2** show things the app doesn't have yet. When you're happy, say **"build it"**: the Engineer builds from the look, the Designer checks the app against the mockup. **Notes on the mockup go straight to the Designer** as one round: it resumes its session for that look, designs every note in one step (`look-apply.py`: adds the CSS, checks it on the page, closes the card) and your open page updates itself: about a minute for plain notes, a few for an image or data. When the rounds stop, a wrap-up card tidies the look.
- **Cards remember:** a bot coming back to a card (sent back, unblocked, out of turns) resumes its session on it, and a card with `Session: <topic>` resumes that bot's last session for the topic (`hermes-worker.py`), so related work doesn't start cold. The Manager picks the topics.

## Adding Discord later
```bash
ssh p330-<name> "nano ~/.hermes/profiles/manager/.env"
```
Add `DISCORD_BOT_TOKEN=<token>` and `DISCORD_ALLOWED_USERS=<your user id>`, save, then restart the gateway (above).

## Remove a project (no undo)
```bash
sudo bash /opt/hermes-template/remove-project.sh story-maker
```
Stops its services and deletes the user, folder, registry entry and firewall rules. It asks you to type the name.

## What's in this repo
| Path | What |
|---|---|
| `host.conf` | Host-wide settings: owner, subnets, model, kanban limits |
| `new-project.sh` | Create a project (run with sudo) |
| `remove-project.sh` | Delete a project (run with sudo) |
| `bootstrap/setup-agent.sh` | Part 2, run automatically as the agent user |
| `template/manager/SOUL.md` | The Manager |
| `template/manager/skills/` | The Manager's template skills: `intake-interview`, `project-takeover`, `work-planning`, `roadmap`, `retro` |
| `template/manager/scripts/` | The Manager's job scripts: `manager-watch.py`, `retro-gate.py` (zero-token gates) |
| `template/workspace/scripts/run-tests.sh` | The one failures-only test command every bot runs |
| `template/import/` | Files used only for an imported project (the onboarding status page) |
| `template/workspace/` | The product repo's starting `AGENTS.md` (team table) and README |
| `template/root-AGENTS.md` | Guardrails for the stock default profile |
| `template/vault/` | The vault skeleton: SCHEMA, status, log, `system/` (overview, role catalogue, change proposals) |
| `template/scripts/` | The project's tools: the vault (`vault-log`, `vault-commit`, `vault-index`, `vault-sweep`, `card-log`, `vault-lint`), hiring (`hire.sh`, `skill-check.py`), imports (`import-project.sh`, `import-survey.py`), the owner queue (`owner-queue.py`), the Mark tool and design links (`feedback-inbox.py`, `feedback-overlay.js`, `mockup.sh`, `demo.sh`, `variant-shot.sh`, `look-check.sh`, `look-apply.py`), card sessions (`hermes-worker.py`), research (`cite-check.py`, `raw-stamp.py`), upkeep (`host-facts.sh`, `workspace-tidy.sh`, `run-eval.sh`) |
| `install-searxng.sh` | One shared self-hosted web search for the bots (run by `new-project.sh`) |
| `tests/` | `test_feedback_inbox.py` (the Mark tool's server), `test_hermes_worker.py` (session resume), `test_look_apply.py` (a design round's apply step), `mark_demo.py` (a page to try the toolbar on) |
| `template/memory.gitignore` | The allowlist for the project memory repo (never secrets or databases) |

Improvements found in a project get copied back here, so the next project starts better. Updating this repo doesn't change existing projects.

## A fresh server
Any recent Ubuntu Server (tested on 26.04) with an admin user that has sudo and your SSH key in `~/.ssh/authorized_keys`. `new-project.sh` installs everything else. Before the first project:
- Check `host.conf`: `OWNER_NAME`, `LAN_SUBNETS` (the networks allowed to reach project apps), and optionally `DISCORD_USER_ID`.
- The firewall: the script adds allow rules but never switches ufw on (that could lock you out). To enable it: `sudo ufw allow OpenSSH && sudo ufw enable`.

## On Windows (WSL2)
The same install runs inside Ubuntu on WSL2 (Windows 11). The installer notices WSL and adjusts: it needs systemd, installs and starts an SSH server for Hermes Desktop, leaves the firewall to Windows (it prints the one rule to add), and uses `localhost` as the address when WSL is in its default NAT mode. Once, before the first project:
1. Install Ubuntu: `wsl --install -d Ubuntu-24.04` in PowerShell, then create your user.
2. Turn on systemd: add to `/etc/wsl.conf` inside Ubuntu
   ```
   [boot]
   systemd=true
   ```
   then `wsl --shutdown` in PowerShell and open Ubuntu again.
3. Optional, so other devices on your network can reach the apps and Mark links: in `%UserProfile%\.wslconfig` on Windows
   ```
   [wsl2]
   networkingMode=mirrored
   vmIdleTimeout=-1
   ```
   (`vmIdleTimeout=-1` stops WSL shutting down when idle), then `wsl --shutdown`. Without mirrored networking everything works from this PC at `http://localhost:<port>`.
4. Keep the bots running when no terminal is open: a Task Scheduler task at log-on that runs `wsl.exe -d Ubuntu-24.04 --exec sleep infinity` (hidden). WSL stops when Windows sleeps or shuts down; the projects' services start again with it.
5. Then run the same one-line install inside Ubuntu. If Windows' own OpenSSH Server already uses port 22 (mirrored mode shares ports), stop it or move one of them.
