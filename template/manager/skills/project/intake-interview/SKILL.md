---
name: intake-interview
description: "Interview the owner: one question at a time, to agreed scope."
version: 1.0.0
author: Project template (adapted from Matt Pocock's grilling and domain-modeling skills, MIT)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [intake, interview, requirements, owner, scope, glossary]
    related_skills: [project-takeover]
---

# Intake interview

Turns what the owner has in their head into decisions written in the vault. Use it for a new project (`phase: setup`), for the gaps a takeover finds (`phase: onboarding`), and for any new idea big enough to need scope. The output is decisions the owner said yes to, not a document.

Credit: adapted from Matt Pocock's `grilling` and `domain-modeling` skills (github.com/mattpocock/skills, MIT). One change on purpose: one question per message, not a round.

## Before the first question
1. Read `00-status.md`, the last 20 lines of `log.md`, `product/` (including `product/out-of-scope/` and `product/ideas.md`) and the board. On a takeover, also read `raw/predecessor/inventory.md` and `system/takeover.md`.
2. Start or reopen the state file `raw/interview-<YYYY-MM-DD>.md` (frontmatter as SCHEMA says; `type: research`). It holds four lists, kept current after every answer:
   - **Decided:** the decision, the owner's words, and the date.
   - **Askable now:** questions only the owner can answer, most important first.
   - **Blocked:** questions that wait on another answer or on research.
   - **Assumed:** anything you are going ahead on without asking. Keep it short; each line is a risk.
3. Move every fact you can look up out of "Askable now": the vault, the repo, the predecessor notes, the web, or a Researcher card. **Never ask the owner a fact.** Ask about goals, priorities, taste, trade-offs and limits.

## The loop
1. **One question per message, asked in the chat.** Give your recommended answer and a one-clause reason ("I'd pick B: it keeps the first slice small"). Offer 2 or 3 options only when they're genuinely different. Then stop and wait. Never send the owner to a file of questions; the state file is your notes.
2. **Ask what changes the plan.** Order: the goal and who it's for → what "done" looks like → hard limits (time, money, platforms, data, legal) → what's out of scope → priorities → how the owner wants to work.
3. **Record each answer the moment it lands:** update the state file (verbatim-ish, the options offered and the pick), then `vault-log.sh manager ingest "<one line>" "[[raw/interview-<date>]]"`.
4. **Settled words go to `product/glossary.md`** right away (term, one-line meaning, words to avoid). Use those words from then on.
5. **"How should it look or feel" becomes a prototype card,** not more questions. A rough mock beats five answers.
6. **Push back once, with the mechanism.** If an answer carries real risk, say what it costs in plain words and recommend; check a platform rule on the web first rather than from memory. Then take the owner's call, write down the trade, and never re-argue it.
7. **Restate after each cluster** ("So: X for Y, done when Z. Right?") and get a yes before building on it.
8. **Before taking on an idea,** check `product/out-of-scope/`. If it was rejected before, say so and why; the owner decides again.
9. **Soft stop after about 12 questions:** "I have enough to propose. Summarise and propose, or keep going?" Stop for good when "Askable now" is empty and "Assumed" holds nothing big.

## Close
1. Write or update `product/<project>.md`: what it is, who it's for, what "done" means, limits, out of scope (one line each, with links to `product/out-of-scope/<idea>.md` for rejected ideas), and links to the interview file. Point to repo docs, don't copy them.
2. Big projects only (several areas, many open decisions): `product/decision-map.md` with three lists, each line linked to its source: **settled**, **open (owner)**, **unknown until researched or prototyped**.
3. Show the owner a phone-length summary and get an explicit yes. Then carry on with the next step of whatever called this skill (the Manager's start-up, or `project-takeover`).

## Style
- Lead with the question. No preamble, no process lecture after the first message.
- Plain words; short enough to read on a phone. Never a list of questions.
- Good ideas that aren't for now go to `product/ideas.md` with one line of why.
- A one-word "yes" to a message that also asked the owner to do something approves the plan only: re-ask the actions as one short numbered list.
- A "not yet" is usually a question: answer that first, then offer the same decision again in one line.

## Pitfalls
- Batched questions get skimmed. One question is what makes each answer usable.
- Asking what the vault, repo or predecessor notes already answer reads as amnesia.
- Early answers are drafts. When the owner refines an idea, update the state file; don't defend the first reading.
- Don't hide assumptions in prose. If it isn't in "Decided", it's in "Assumed", where the owner can see it.

## Done when
- [ ] Every owner answer is in the state file and logged.
- [ ] "Askable now" is empty, or the owner chose to stop.
- [ ] `product/<project>.md` (and the glossary) match what was agreed, and the owner said yes.
