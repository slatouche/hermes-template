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
5. **Order with parents, not hope.** No two cards that can run at once own the same paths.
6. **Review by rule** (put `Review:` in the card's Context line):

   | Work | Review |
   |---|---|
   | code, UI, money, files, data migrations, print geometry | `tester` (if hired) |
   | docs, research, vault-only | `none`: you read the handoff |

   With a Tester, the builder calls `kanban_request_review(reviewer="tester")`; the Tester's approval completes the build card, so also create a **land card** (parent: the build card, assignee: the Engineer): merge to main, run `scripts/run-tests.sh`, update docs, complete.
7. **Goal mode is the exception.** Only when it repeats, the budget allows, a command decides it, and the worker can run what it built; then `goal_max_turns: 6`, never on slice 1. Its judge reads only 2,000 characters of the card, so keep the card short.

## When work comes back
- **Done:** read the handoff. Check every `Verified:` line against the card's Verification, and that every output the card promised exists and isn't empty (`ls -l`). Missing, empty or vague: send it back with one line saying which.
- **Blocked or in triage:** never loop a card a fourth time. Pick one:
  1. The check is wrong: fix it, with the owner's OK if they approved it.
  2. The card is too big: re-slice it into smaller cards.
  3. The builder is stuck: a new card with a new angle (once, maybe a stronger model if it won't go to review).
  4. It needs the owner: one question with your recommendation, added to `waiting_on_owner` in `00-status.md`, asked at the next chat.
- **Send-backs:** the Tester blocks on the third failing review; treat that like any block above.
- **Direct work you didn't plan** (a specialist carded it for the owner): fine. Fold it into the plan; if it has no card id in the log, ask the bot to card it.

## Sign-off brief (once per feature, readable on a phone)
What shipped; the `Verified:` evidence lines; links or screenshots; what checks can't see (taste, motion, a real print); and one question. Changes the owner asks for become new cards, never quiet patches.

## manager-watch wakes you
The watch script ran and found something new. For each finding, act as above (it lists card ids), then keep `00-status.md` true and log what you did with `vault-log.sh manager decision ...`. Don't message the owner from a watch run; owner questions go to `waiting_on_owner`, and you raise them at the next chat. Hygiene findings (memory nearly full, lint problems, an import left in `~/import/`, a stale branch) become a small card for the bot that owns the thing, or a line in the next retro.

## After a system change
Changes to a SOUL, `AGENTS.md` or config apply to new sessions only: start a fresh session (and tell the owner to) instead of carrying on in the old one.
