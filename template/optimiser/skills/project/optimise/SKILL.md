---
name: optimise
description: "Optimise the team: evidence pack to measured, tested proposals."
version: 2.0.0
author: Project template (categories adapted from Matt Pocock's retro skill, MIT)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [optimise, retro, speed, pipeline, lessons, skills, memory, upkeep]
    related_skills: []
---

# Optimise

Use when the nightly `optimiser-review` job wakes you with an evidence pack, when the Manager cards you a question ("why is X slow?"), or when the owner asks "what have we learned?". The aim: a team that gets faster and more reliable and stays lean. Every change is earned by evidence, tested on a copy, and where possible removes something.

## 1. Read the evidence (no guessing)
- The pack (`optimiser-gate.py`): per bot, cards done with their steps, model and tool seconds and context size; outliers; repeated card shapes; work done by the wrong role; the owner's chat reply times; builds and how each stage went; send-backs and blocks; skills changed; memory fill; a model change.
- Open what the pack points at: `hermes kanban show <id>` (comments, block reasons, handoffs), the bot's own log (`references/card-speed.md` has the greps), the build's history (`~/.hermes/builds/<slug>.json`).
- The owner's corrections since your last run: `grep -iE "owner|seb" ~/vault/log.md | tail -40` and their chat turns in the Manager's log (`grep "conversation turn:.*platform=desktop" ~/.hermes/profiles/manager/logs/agent.log | tail`). A correction the owner had to make twice is a finding.
- Compare with your last measurements in `vault/system/optimiser/`.

## 2. Look for these patterns (`references/patterns.md` has each with how to spot it and the usual fix)
- **The same overhead on every card** (a review, a full suite, a merge, a restart per card when once per build would do).
- **A deterministic step done by a model** (merging, landing, re-running checks, copying files, a status read): script it.
- **Reading at the start of every turn** that a pack or the card could hand over.
- **The wrong role doing the work**, or the owner asked what the team could decide.
- **Big sessions** (context over ~120k on most turns), cold starts, one slow tool call, a look (`vision_analyze`) where a number answers.
- **Loops:** send-backs, the same check failing, a build failing more than once, a card re-run.
- **Instructions not followed** or followed only sometimes: make it a check or a script, not more prose; **dead instructions** the model follows anyway: remove them.

## 3. Sort what you find (Pocock's categories)
- **A mechanical mistake** (a format slip, a forgotten step a command could catch): an **automated check** (a test, a lint rule, a script), not a prose rule.
- **A standard the reviewer should hold:** a line in that reviewer's role, not in everyone's context.
- **A habit the whole team needs:** a lesson in `system/lessons.md` (one line, date, card id).
- **A wrong or dead instruction** in `AGENTS.md`, a SOUL, a skill or a lesson: move it to where it belongs, or delete it.
- **A procedure a bot keeps reinventing:** a skill for that bot (or grow an existing one).
- **A step a model does that a script could:** a script, and the bot's instruction shrinks to calling it.

## 4. Upkeep, each run
- **Memory over 85%:** propose a card for that bot: "merge your MEMORY.md; keep what the owner said; drop progress and inventories".
- **Skills:** duplicates merged, unused bot-written ones left for the Curator (it archives them after 60 days). Template skills (`project/*`) change only by proposal with `promote: template`.
- **Vault:** pages the lint calls stale get updated or `status: superseded`; nothing deleted.
- **Tests:** the suite still passes and grew with the features; tests for removed behaviour are gone.
- **Lessons near 40:** merge or retire lines; a lesson that became a check is removed.
- **Model changed** (the pack says so): for each skill, run its task once without the skill on a copy and cut what the new model follows unaided; run every bot's eval (`run-eval.sh <bot>`) and compare with the last results.

## 5. Test on a copy
Before proposing, show the change works: run the changed script on a copy in `scratch/`, a fixture card on the `rig` board (blocked at creation), a test copy of the design view (`design-view.py --port <spare> --layer <a copy> --no-cards`), or the bot's eval before and after a SOUL or skill change (`~/.hermes/scripts/run-eval.sh <bot>`; never write a change from the eval's own prompts). Record the before and after numbers.

## 6. Propose (at most 5 per run)
One file per change: `system/changes/<YYYY-MM-DD>-<slug>.md` with frontmatter `status: proposed`, `author: optimiser`, `promote: template` when every project would gain, and the sections **Evidence**, **Cause**, **Change** (the exact diff or file), **Removes**, **Gain** (measured or estimated, say which), **Tested** (how, with numbers), **Affects**, **Rollback**. Never touch approved acceptance checks or test plans. Then one card for the Manager: `Screen Optimiser proposals (<n>)`, a line per proposal, `Shape: quick`. Update your page in `system/optimiser/` and stop.

## Done when
- [ ] Every outlier, loop and repeated shape in the pack has a cause written down (even "no change needed").
- [ ] Each proposal has evidence, a test on a copy, and something considered for removal.
- [ ] `system/optimiser/` holds this run's numbers; the Manager has its card (or there was nothing to propose).
