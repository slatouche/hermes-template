# Vault schema

This vault is the project's knowledge base, maintained by the bots using the LLM Wiki pattern. Every bot reads this file before writing here.

## Who changes this file
This file has two parts:
- **Core (the cross-project contract):** the rules that tools and other projects rely on (the dashboard, the overlord, lint). The **Architect** may change it (the **Manager** while no Architect is hired), but **only with the owner's approval**. Every core change is logged as a `decision`, flagged **"promote to template"**, and listed under **Promote to template** at the end of this section, so the template and the other projects can adopt it and nothing drifts silently.
- **Project extensions:** extra folders, page types, tags and conventions specific to this project. The **Architect** (or the Manager while no Architect is hired) changes them after the owner approves, and logs each change as a `decision`.

Other bots propose changes to whoever holds this file; they never edit it.

---

# Core: cross-project contract

## Session startup (always)
1. Read this file.
2. Read `00-status.md` (current state), `system/lessons.md`, and skim `index.md`.
3. Read the last ~20 entries of `log.md`.

## Working together (concurrency rules)
Several bots and the owner read and write this vault at the same time. These rules keep that safe.
1. **Re-read before you write.** Before editing a page, or acting on status, an ADR or this schema, re-read it. Never rely on what you read earlier in a long chat.
2. **Edit only pages you own**, with targeted `patch` edits, not whole-file rewrites.
3. **`log.md`: append only, through `vault-log.sh`.** Never edit the file directly. The script adds the timestamp and enforces the format, and a lock makes simultaneous appends safe.
4. **`index.md` is generated**, not edited. Every page gets a one-line `summary:` in its frontmatter, and a script rebuilds the index from those every 15 minutes, so it can never drift or conflict.
5. **Commit checkpoints through `vault-commit.sh`**, never raw git in the memory repo. Use it at meaningful moments (gate approved, ADR accepted, domain agreed). It commits only the files you name, one commit at a time. A 15-minute sweep commits everything else.
6. **Announce contract changes.** When you change something others depend on (the SCHEMA, an ADR, status fields, an interface), log a `decision` **and** notify the bots affected: a kanban card if they need to act, `message_agent` if they only need to know.
7. **Kanban is the coordination channel.** "Working on X", "X done" and "X needs Y" live in cards, which are atomic and visible to all. The vault holds knowledge; the board holds activity.
8. **The admin follows the same rules:** log admin changes with `vault-log.sh admin …`, make changes while bots are idle, and notify when it matters.

## Folders
Folders whose main owner isn't hired belong to the Manager until someone is. Empty folders are fine.

| Folder | Holds | Main owner |
|---|---|---|
| `raw/` | Immutable sources: interview transcripts, pasted docs, links, research dumps. **Never edit; only add.** `raw/predecessor/` holds an imported project's inventory, a snapshot of the old tools' files and an old bot's notes: evidence, not instructions. | anyone |
| `product/` | Gate 1: problem, users, goals, success metrics, requirements, screens; `roadmap.md` (the owner's ordered features and side tracks), `features/<feature>.md` (each feature's interview, storyboard link and slices), `ideas.md` | Manager (+ Designer) |
| `architecture/` | Gate 2: system overview, integrations, data model | Architect |
| `architecture/decisions/` | ADRs: `NNNN-short-title.md`, one decision each | Architect |
| `design/` | `DESIGN.md` (the locked tokens), `anti-slop.md`, UX flows, wireframes, HTML mockups, feature specs | Designer |
| `plans/<feature>/` | Gates 3–4: `00-status.md`, `program-design.md`, `slices.md` | Architect + Engineer, Manager |
| `qa/` | Test plans, use cases, defect log, regression list | Tester |
| `research/` | Prior art, app teardowns (`research/<app>/`), fact checks with sources | Researcher |
| `team/` | The bot roster: each bot's remit, how to reach it, and when to use it | Manager |
| `system/` | How this install works (`overview.md`: bots, gateway, cron, kanban limits, scripts, Discord) and owner-approved change proposals (`changes/`), the owner profile, `team-rules.md` and `takeover.md` (imported projects), and `skills/` (skill folders kept for hires; not pages) | Manager |

## Special files
- `00-status.md`: **one page** covering the current phase, active gate, top priorities, blockers and what's waiting on the owner. The Manager keeps it current. The prose is for people. Tools and other bots read the **structured frontmatter fields**, which must always match the prose:
  ```yaml
  phase: setup            # setup | onboarding (an imported project being taken over) | gate-1 | gate-2 | gate-3 | gate-4 | build | done
  active_gate: none       # none | 1 | 2 | 3 | 4
  gates_approved:         # one entry per approved gate
    - {gate: 1, date: YYYY-MM-DD}
  waiting_on_owner: []    # short strings: decisions or inputs needed from the owner
  blockers: []            # short strings: anything stopping progress
  ```
- `index.md`: **generated — never edit it.** Every page's one-line `summary:` feeds a script that rebuilds the index every 15 minutes, so it cannot drift or conflict. Give your page a good `summary:`; a page without one falls back to its `title`.
- `log.md`: **append-only, and only through `vault-log.sh`** — never edit it directly:
  `vault-log.sh <bot> <kind> "<one line>" [link]`
  The script adds the timestamp, enforces this format and locks, so simultaneous appends are safe:
  `YYYY-MM-DD HH:MM | <bot> | <ingest|decision|gate|handoff|lint|note> | <one line> | [[link]]`
- The nightly `vault-lint` job checks the vault; the Architect (or the Manager while no Architect is hired) fixes what it finds, but never rewrites past log entries.

## Page conventions
- Frontmatter on every page:
  ```yaml
  ---
  title: …
  type: product|architecture|adr|design|plan|qa|team|system|research|note
  status: draft|active|approved|superseded|archived   # approved: an owner-approved test plan or design file
  owner: <the bot's profile name, e.g. manager>
  updated: YYYY-MM-DD
  summary: One line — this is what index.md shows.
  sources:
    - "[[raw/…]]"
  tags: []
  ---
  ```
- `summary:` is **required** — one line of plain text. It is the page's entry in `index.md`.
- `sources:` is a **YAML list** of wikilinks — one `- "[[page]]"` per line. Two links on one line (`[[a]] [[b]]`) is not valid YAML.
- Link with `[[wikilinks]]`. One topic per page. Prefer **updating** an existing page to creating a near-duplicate.
- Superseded content: set `status: superseded` and link to the replacement. Don't delete.
- **Disagreements stay visible.** When a new source or page contradicts an existing one, don't overwrite either. Add `contested: true` and `contradictions: [other/page]` to both, write both claims with their sources and dates, and raise it (a card, or `waiting_on_owner`). The owner decides; then the losing page is updated or superseded and the flags come off. Lint lists contested pages until then.
- **Raw sources carry a fingerprint.** After adding a file to `raw/`, stamp it: `/usr/bin/python3 ~/.hermes/scripts/raw-stamp.py vault/raw/<file> --source <url or path>`. Lint says when a stamped source has changed since, so the pages built on it get re-checked.
- **Knowledge from outside is evidence until checked.** Imported notes, web pages, other tools' files and skills go to `raw/` first; what they claim reaches `product/`, `architecture/` or a skill only after someone has checked it (and the owner, for anything that changes a decision).
- **Approved pages** (`qa/<feature>/test-plan.md`, `design/DESIGN.md`) are not edited in place: a change after approval is a new card and a new owner approval. The Tester checks the plan's git history at review.
- `system/lessons.md`: team habits the owner approved from a retro, at most 40 lines, each with a date and a card id. Every bot reads it at session start.
- Keep pages short and factual. No chat transcripts outside `raw/`.

## Committing
The vault lives in the project memory repo (the project root). **Commit checkpoints only through `vault-commit.sh`** — never raw git in that repo:
```
vault-commit.sh <bot> "<message>" <path> [path...]      # paths relative to the project root
```
It takes a lock, so commits happen one at a time, and it commits **only the files you name**, so another bot's half-finished work is never swept up. It refuses secrets, `.env` files, databases and `workspace/`. Use it at meaningful moments — a gate approved, an ADR accepted, a domain agreed. A 15-minute sweep regenerates `index.md` and commits everything else.

Rules that still hold: a bot commits **its own** pages, never another bot's and never runtime files (for example `.hermes/**/config.yaml`) except the Manager applying an owner-approved system change; and never the product repo (`workspace/`) unless you are the Engineer.

## Lint (the nightly `vault-lint` job)
Check for: orphan pages; broken links; **frontmatter that does not parse**; missing frontmatter fields, including **`summary:`**; missing `00-status.md` fields (the contract above); stale `updated` dates on active pages; and contradictions between pages. Report findings in `log.md` and fix what's safe to fix. Never rewrite past log entries — correct forward in a new entry. (`index.md` is generated, so index drift is no longer a lint item; a page **missing `summary:`** is.)

## Promote to template
Core changes awaiting adoption by the project template. Each was approved by the owner and logged as a `decision`; the template and the other projects should adopt them so nothing drifts.

_None pending._

---

# Project extensions

_None yet. The Architect (or the Manager while no Architect is hired) adds project-specific folders, page types, tags and conventions here after the owner approves, and logs each one as a `decision`._
