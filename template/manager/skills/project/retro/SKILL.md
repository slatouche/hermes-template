---
name: retro
description: "Weekly retro: evidence to at most 5 changes."
version: 1.0.0
author: Project template (categories adapted from Matt Pocock's retro skill, MIT)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [retro, learning, lessons, skills, memory, upkeep]
    related_skills: [work-planning]
---

# Retro

Use when the `weekly-retro` job wakes you with an evidence pack, or when the owner asks "what have we learned?". The aim is a team that gets better and stays lean: every change is earned by evidence, and where possible something is removed for each thing added.

## 1. Read the evidence (no guessing)
- The pack: cards with send-backs or blocks, bot-written skills that are new or changed, memory fill, cards done, test count, lessons count.
- For each troubled card: `hermes kanban show <id>` (comments, the block reason, the handoffs). What actually went wrong?
- For each new or changed skill: read it. Is it right, is it a duplicate of another, is it used?
- The owner's corrections in the log and in `raw/` since the last retro.

## 2. Sort what you find (Pocock's categories)
- **A mechanical mistake** (a format slip, a forgotten step a command could catch): make it an **automated check** (a test, a lint rule, a line in `scripts/run-tests.sh`), not a prose rule.
- **A standard the reviewer should hold:** a line in the Tester's role or the review lenses, not in everyone's context.
- **A habit the whole team needs:** a lesson in `system/lessons.md` (one line, date, card id).
- **A wrong or dead instruction** in `AGENTS.md`, a SOUL, a skill or a lesson: move it to where it belongs, or delete it.
- **A procedure worth repeating** that a bot keeps reinventing: a skill for that bot (or merge it into an existing one).

## 3. Upkeep, every retro
- **Memory over 85%:** a small card for that bot: "merge your MEMORY.md; keep what the owner said; drop progress and inventories".
- **Skills:** duplicates merged, unused bot-written ones left for the Curator (it archives them after 60 days unused). Never edit template skills (`project/*`).
- **Vault:** pages the lint calls stale get updated or `status: superseded`; nothing deleted. Contested pages and changed sources (lint advisories) go to the owner as decisions.
- **Tests:** the suite still passes and has grown with the features; tests for removed behaviour are gone.
- **Workspace:** no orphan files, scripts or docs left from finished work.
- **Lessons near 40:** merge or retire lines; a lesson that became an automated check is removed.
- **Model changed** (the pack says so): for each template and bot-written skill, run its task once without the skill and cut instructions the new model follows unaided. Run every bot's eval (`run-eval.sh <bot>`) and compare with the last results.

Before applying any approved change to a SOUL or a skill, run that bot's eval (`~/.hermes/scripts/run-eval.sh <bot>`) before and after, and keep the change only if the answers stayed as good or got better. Never write a change from the eval's own prompts; they're a held-back check.

## 4. Propose (at most 5 changes)
Write `system/changes/<YYYY-MM-DD>-retro.md`: each change with its evidence (a card id or the owner's correction), the exact edit, who it affects, and what it removes. Never touch approved acceptance checks or test plans. Add one line to `waiting_on_owner` in `00-status.md` ("retro: 3 changes to approve"), and log it.

At the next chat, show the owner a phone-length summary and ask for a yes per change. Apply only what's approved, the usual way (system changes: idle bots, a `decision` log line, a checkpoint, a fresh session for the affected bots). Lessons go into `system/lessons.md` the same day.

## Done when
- [ ] Every troubled card in the pack has a cause written down (even "no change needed").
- [ ] The change page has at most 5 changes, each with evidence, and nothing grew without something considered for removal.
- [ ] Upkeep cards exist for anything over its limit.
