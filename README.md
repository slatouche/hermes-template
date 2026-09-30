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
On the server, logged in as your admin user (the one with sudo):
```bash
git clone <this repo's URL> ~/hermes-template    # once; later just: git -C ~/hermes-template pull
sudo bash ~/hermes-template/new-project.sh story-maker
```
You're asked at most three things: the OpenCode key, the Discord bot token (Enter skips Discord), and your Discord user ID (skipped if `DISCORD_USER_ID` is set in `host.conf`). Keys are typed hidden and go straight into the project's `.env`. Everything else is automatic, **including installing Hermes**. The first run on a fresh server also installs the Ubuntu packages the bots need. Allow 5–10 minutes.

What it does:
| Part | As | Steps |
|---|---|---|
| 1 | root | installs missing Ubuntu packages (git, Python YAML, ripgrep, ffmpeg, the headless browser's libraries); registry entry (next number → ports `1NN00-1NN99`); user `agent-<name>` with home `/srv/projects/<name>`; you added to its group; your SSH keys copied (for Hermes Desktop); linger; firewall rules for the app ports |
| 2 | `agent-<name>` | installs Hermes; keys; default profile config (model, kanban limits, API server); vault from the template; scripts; `workspace/` repo; the **Manager** profile (SOUL, display name, Hermes Project, Discord); kanban board; `vault-sweep` and `vault-lint` jobs; the project memory repo; the gateway service |

It's safe to re-run if something fails part-way: finished steps are skipped.

At the end it prints an SSH config block. Add it to `~/.ssh/config` on your PC, then:
- **Hermes Desktop:** add an SSH connection to `p330-<name>` and open the Manager.
- **Discord:** DM the bot or post in the project channel. The Manager sees a new project (`phase: setup`) and starts the intake interview.

## How it grows
- The Manager proposes each hire in `vault/system/changes/`. The catalogue in `vault/system/roles/` has an Architect, Engineer, Designer and Tester. For anything else (a Writer, say) the Manager drafts a role from `_guide.md`.
- After you say yes, the Manager runs `~/.hermes/scripts/hire.sh <role> [--channel <id>]`. For a bot with its own Discord channel, create the channel, give the Manager its ID, and restart the gateway afterwards:
  ```bash
  ssh p330-<name> "systemctl --user restart hermes-gateway"
  ```
- All changes to how the team works (SOULs, config, jobs) go through the same propose → approve → apply loop. The Manager never touches `.env`, sudo or the gateway.
- `vault/system/overview.md` in each project explains how its install works.

## Adding Discord later
```bash
ssh p330-<name> "nano ~/.hermes/profiles/manager/.env"
```
Add `DISCORD_BOT_TOKEN=<token>` and `DISCORD_ALLOWED_USERS=<your user id>`, save, then restart the gateway (above).

## Remove a project (no undo)
```bash
sudo bash ~/hermes-template/remove-project.sh story-maker
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
| `template/workspace/` | The product repo's starting `AGENTS.md` (team table) and README |
| `template/root-AGENTS.md` | Guardrails for the stock default profile |
| `template/vault/` | The vault skeleton: SCHEMA, status, log, `system/` (overview, role catalogue, change proposals) |
| `template/scripts/` | `vault-log`, `vault-commit`, `vault-index`, `vault-sweep`, `vault-lint`, `hire.sh` |
| `template/memory.gitignore` | The allowlist for the project memory repo (never secrets or databases) |

Improvements found in a project get copied back here, so the next project starts better. Updating this repo doesn't change existing projects.

## A fresh server
Any recent Ubuntu Server (tested on 26.04) with an admin user that has sudo and your SSH key in `~/.ssh/authorized_keys`. `new-project.sh` installs everything else. Before the first project:
- Check `host.conf`: `OWNER_NAME`, `LAN_SUBNETS` (the networks allowed to reach project apps), and optionally `DISCORD_USER_ID`.
- The firewall: the script adds allow rules but never switches ufw on (that could lock you out). To enable it: `sudo ufw allow OpenSSH && sudo ufw enable`.
