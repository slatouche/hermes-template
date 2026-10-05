---
name: work-planning
description: "Cut cards, route review, unstick blocked work."
version: 1.0.0
author: Project template (card brief adapted from Matt Pocock's to-tickets skill, MIT)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [kanban, cards, planning, review, escalation, triage]
    related_skills: [intake-interview, retro]
---

# Work planning

Use when turning an agreed plan into cards, when a card comes back blocked or in triage, when `manager-watch` wakes you, or when a feature is ready for the owner's sign-off. The card format and the builder's rules are in `AGENTS.md` (every bot loads them); this skill is how you, the Manager, use them.

## Cutting cards
1. **One outcome per card, smallest first.** Slice 1 is always a plain card (no goal mode). If you can't write the Verification, the card isn't ready: ask, prototype or research first.
2. **Verification comes from the test plan** (`qa/<feature>/test-plan.md` when there's a Tester), copied verbatim. The owner approves the plan's checks once, in plain words, **before** the build starts: create the build card with `initial_status="blocked"` (or a parent the approval unblocks), show the owner the checks as a short list, then set the plan to `status: approved` and unblock. Without a Tester, write 2–5 checks yourself: a command and its exact expected output, plus one "reachable from the running app" check.
3. **Title at most 50 characters, no trailing punctuation** (the branch name is built from it; a long one can end in "." and git refuses it).
4. **Settings:** `idempotency_key` (so a retry doesn't duplicate), `max_runtime_seconds` 3600 for code, 1800 for research and docs; workspace `worktree` for code, `dir` on `~/workspace` for docs and vault work; `skills=[...]` only for task-specific skills. Don't pin a model on a card that goes to review (the pin applies to the review run too).
5. **Things the owner opens stay up.** When a card builds or changes something the owner uses (an app, a web page, an API), its Verification includes reaching it from the owner's network (`http://<host address>:<port in the project's block>`), and it runs as a systemd user service (`~/.config/systemd/user/<name>.service`, `Restart=always`, enabled, so it survives crashes and reboots; no sudo needed). After a change lands, the service is restarted. A process started in a terminal is gone when the card ends. The same card adds a **review link**: a line `<app port + 50> <app port> <name>` in `~/.hermes/scripts/review-mirrors.conf`, then `systemctl --user restart feedback-inbox`; the owner reviews and marks it up at `http://<host>:<app port + 50>/`.
6. **Order with parents, not hope.** No two cards that can run at once own the same paths.
7. **Review by rule** (put `Review:` in the card's Context line):

   | Work | Review |
   |---|---|
   | code, UI, money, files, data migrations, print geometry | `tester` (if hired) |
   | docs, research, vault-only | `none`: you read the handoff |

   With a Tester, the builder calls `kanban_request_review(reviewer="tester")`; the Tester's approval completes the build card, so also create a **land card** (parent: the build card, assignee: the Engineer): merge to main, run `scripts/run-tests.sh`, update docs, complete.
8. **Goal mode is the exception.** Only when it repeats, the budget allows, a command decides it, and the worker can run what it built; then `goal_max_turns: 6`, never on slice 1. Its judge reads only 2,000 characters of the card, so keep the card short.

## When work comes back
- **Done:** read the handoff. Check every `Verified:` line against the card's Verification, and that every output the card promised exists and isn't empty (`ls -l`). Missing, empty or vague: send it back with one line saying which.
- **Blocked or in triage:** never loop a card a fourth time. Pick one:
  1. The check is wrong: fix it, with the owner's OK if they approved it.
  2. The card is too big: re-slice it into smaller cards.
  3. The builder is stuck: a new card with a new angle (once, maybe a stronger model if it won't go to review).
  4. It needs the owner: one question with your recommendation, added to `waiting_on_owner` in `00-status.md`, asked at the next chat.
- **Send-backs:** the Tester blocks on the third failing review; treat that like any block above.
- **Direct work you didn't plan** (a specialist carded it for the owner): fine. Fold it into the plan; if it has no card id in the log, ask the bot to card it.

## The owner queue
Everything that needs the owner's decision, answer, approval or hands is **a card blocked as `needs_input`** (or `capability` for things only a person can do). One place, nothing lost, nothing times out.
- **Bots raise it:** `kanban_block(kind="needs_input", reason="<one question>. Options: ... I recommend ... because ...")`, then stop. Other cards keep running; only cards that depend on this one wait.
- **You raise approvals the same way:** a proposal (system change, hire, retro change, gate, design stop) gets a card titled `Owner: <the decision>`, assigned to you, created with `initial_status="blocked"`, then blocked as `needs_input` with the question and a link to the proposal page.
- **Never chase:** no reminders, no escalation, no re-asking in later cards. `00-status.md`'s `waiting_on_owner` just lists the card ids.
- **Going through it with the owner:** when they ask "what needs me?", say `/queue`, or start a chat while items wait: show the list (`/usr/bin/python3 ~/.hermes/scripts/owner-queue.py`, oldest first, one line each with your recommendation), then take them **one at a time**. Accept batch answers ("yes to 1 and 3"). For each answer: a comment on the card with the owner's words, a `decision` log line, the change applied or the card unblocked, and the item is off the list. "Later" leaves it waiting, untouched.

## Passing on a design pick
When the owner picks a direction (or a wireframe or mockup option), the card that records it carries a check in its Verification: `ls ~/vault/design/<step folder>/` shows only the picked option, and the others are under `raw/design-archive/` (outside the served folder; their review-link URLs return 404). Check it in the handoff before the next design card starts. Archived options stay in git and in the archive; nothing is lost, but only one path stays live.

## The owner's notes from the Mark overlay
Notes land in `raw/feedback/` (`status: open`, with the page, the element's selector and text, the screen size). For each: a card for the bot that owns it (Designer for how it looks or reads, Engineer for what's broken), with the note linked as context and its selector in the Verification; then set the note's `status: done` and `card: t_...`. Similar notes on one screen become one card. A note that's really a decision goes to the owner as a question. `manager-watch` wakes you when new notes arrive.

## Sign-off brief (once per feature, readable on a phone)
What shipped; the `Verified:` evidence lines; links or screenshots; what checks can't see (taste, motion, a real print); and one question. Changes the owner asks for become new cards, never quiet patches.

## manager-watch wakes you
The watch script ran and found something new. For each finding, act as above (it lists card ids), then keep `00-status.md` true and log what you did with `vault-log.sh manager decision ...`. Don't message the owner from a watch run; owner questions go to `waiting_on_owner`, and you raise them at the next chat. Hygiene findings (memory nearly full, lint problems, an import left in `~/import/`, a stale branch) become a small card for the bot that owns the thing, or a line in the next retro.

## After a system change
Any edit to `AGENTS.md` (or a `CLAUDE.md` pointer) shows the owner an approval prompt per write: draft the full file in `~/scratch/`, then write it once.

Changes to a SOUL, `AGENTS.md` or config apply to new sessions only: start a fresh session (and tell the owner to) instead of carrying on in the old one.
