---
name: work-planning
description: "Cut cards, route review, unstick blocked work."
version: 1.1.0
author: Project template (card brief adapted from Matt Pocock's to-tickets skill, MIT)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [kanban, cards, planning, review, escalation, triage]
    related_skills: [intake-interview, retro]
---

# Work planning

## When to Use
Use when turning an agreed plan into cards, when a card comes back blocked or in triage, when `manager-watch` wakes you, when the owner asks why a card is slow or what a bot spent its time on, or when a feature is ready for the owner's sign-off. The card format and the builder's rules are in `AGENTS.md` (every bot loads them); this skill is how you, the Manager, use them. Detail lives in `references/`: `checks.md` (writing checks that prove something), `kanban-cli.md` (CLI shapes, boards, who gets notified), `card-speed.md` (where a card's time goes), `real-input-verification.md` (driving a control like a person), `live-update-verification.md` (proving a page updated without reloading).

## Cutting cards
0. **Route by who owns it, one card, no relay.** A UI change the owner asks for (look, layout, wording, what a screen shows) belongs in the design view: point them there (or send it as a note yourself), and it lands in seconds; once agreed it's built with the rest. No card, no Tester. A code fix or a feature is an **Engineer** card. **Building is never the Tester's job:** no Engineer yet and real code to write? Propose hiring one rather than handing it to the Tester or the Designer. Small choices inside a request are the bot's to make (it says which it picked).
1. **Say the shape on the first line** (`Shape: quick | scoped | needs_owner | needs_breakdown`). Only you create `needs_breakdown` cards, and you cut them into `quick`/`scoped` cards; a worker that finds its card bigger than it looked stops and messages you one line (`needs_breakdown: <what is really in it>`). Bots self-card only `quick` work in their own domain. Several similar quick jobs **collate into one card with a checkbox list**, each item with its own check. The handoff's first line says what the shape turned out to be (`quick as carded` / `bigger: needed the funnel`).
2. **One outcome per card, smallest first, about 15 minutes: 30-60 steps** (a bot has 90; hitting the cap resumes but costs a restart). A bot works one card at a time, so a long card holds up everything behind it. A build across several screens is a card per screen, in order, on one `Session:` topic; so is work that crosses layers (storage, serving, loading data, a service and its review link). Slice 1 is a plain card (no goal mode). If you can't write the Verification, the card isn't ready: ask, prototype or research first.
3. **Verification comes from the test plan** (`qa/<feature>/test-plan.md` when there's a Tester), copied verbatim; without one, write 2-5 checks yourself: a command and its exact expected output, plus one "reachable from the running app" check. The rules that matter most (the rest in `references/checks.md`):
   - **Run each check yourself before it goes in the card** and note what it returns now. A wrong port, path or route is the common error.
   - **A check must be able to fail:** run it against the blocked case (a cover over the control, the build before the fix) and see it fail.
   - **A control the owner clicks or types into is proved with real input** (`ui-check.sh --click / --type`), never by assigning `.value` or calling `.click()`.
   - **Numbers before pictures.** A colour, size, gap, count or overflow is read from the DOM in one call; a look (`vision_analyze`, 30-60 s) only for what only a look answers, once, on the finished change, cropped.
   - **A layout complaint is reproduced at the owner's widths** (1280, 1100, 900, 760) before anything changes.
   - **No check depends on another card running**, and **no check writes into a real channel**: a test of the design view runs on a throwaway copy of it (`design-view.py --port <spare> --layer <a copy> --no-cards`), never the owner's; a fixture card goes on the `rig` board, blocked at creation, so it can never ring the owner. Close what a check created as part of the check.
4. **Design notes don't need cards:** the owner's notes in the design view are done there, in seconds, with no card. What reaches you from it: function changes (a card each), behavior proposals to review, and the build after Agreed (see "The design view" below).
5. **Give related cards one `Session:` topic** (`<area>:<thing>`, e.g. `engineer:deck-view`) so the same bot resumes what it knows. Unrelated work, a new topic; a stale or confused topic, `Session: new <topic>`. A long session does slow later cards, but the fix is compaction (it summarises a big session, and tidies one 45 minutes after work stops), never a fresh topic for speed: if rounds on a big session stay slow, tell the owner and propose a lower compaction threshold. `~/.hermes/scripts/hermes-worker.py --topics` (with `HERMES_HOME` set to the bot's profile) lists them.
6. **Title at most 50 characters, no trailing punctuation** (the branch name is built from it).
7. **Settings:** `idempotency_key`; `max_runtime_seconds` 3600 for code, 1800 for research and docs; workspace `worktree` for code, `dir` on `~/workspace` for docs and vault work; `skills=[...]` only for task-specific skills. Don't pin a model on a card that goes to review. The title is positional on `create`; more in `references/kanban-cli.md`.
8. **Things the owner opens stay up.** A card that builds something the owner uses (an app, a page, an API) checks it from the owner's network (`http://<host address>:<port in the project's block>`) and runs it as a systemd user service (`Restart=always`, enabled; restarted after a change). The design view (`<API port + 51>`) already serves the front end from `main` with mock data, so design never touches real data; nothing to add per app. The real app gets no review link.
9. **Order with parents, not hope.** No two cards that can run at once own the same paths.
10. **Review by rule** (`Review:` in the card's Context line). **A bot runs only when the work needs it:** every review is a model run, a slot and minutes of wall clock.

    | Work | Review |
    |---|---|
    | new behaviour, a state machine, data, money, files, migrations, permissions, print geometry, security | `tester` (if hired): functionality, against the test plan's cases |
    | a UI change the owner asked for, or UI built from the agreed design | `designer`: the Engineer lands it, the Designer checks the running app and approves |
    | a colour, copy line, doc line, rule; other code | `none`: the author's `Verified:` lines are the proof; the owner's look is the review for design |

    **The Tester tests what the software does:** use cases and the test plan's cases, posed so a run passes or fails. Whether a test plan includes a UI check (a control reachable, a flow that works at a width) is your call when you write the plan, and it is still a behaviour check (`ui-check.sh --click/--type`), never a judgement on looks. Never wake a bot to re-confirm a check the card already ran. With a Tester, the builder calls `kanban_request_review(reviewer="tester")`; the approval completes the build card, so also create a **land card** (parent: the build card, assignee: the Engineer): merge to main, run `scripts/run-tests.sh`, update docs, complete.
11. **Goal mode is the exception.** Only when it repeats, the budget allows, a command decides it, and the worker can run what it built; then `goal_max_turns: 6`, never on slice 1. Its judge reads only 2,000 characters of the card.

## Fixing a defect the owner reports
Card the **mechanism**, not the patch: name what let the bug through and change that (a hand-kept list every new panel must join becomes a structural rule; a check that assigned a value becomes one that types), and say which class of bug it prevents. Doing the same cleanup by hand a third time is the same signal. Two exceptions: when the owner is standing in front of the broken thing, fix and verify it yourself now and card only the hardening; when a card is still writing that file, comment on the card and re-check after it finishes.

## When work comes back
- **Done:** check every `Verified:` line against the card's Verification and that every promised output exists and isn't empty (`ls -l`). Missing, empty or vague: send it back with one line saying which. Also:
  - **What did the check leave behind?** If it sent, saved, answered or dispatched anything through a channel the owner uses (`ls -lt vault/raw/feedback/`, the board), stop any round it spawned (`hermes kanban complete <id> --force`) and withdraw it before telling the owner it landed.
  - **Are earlier fixes still there?** When the card touched a file another card recently fixed (a shared script, the overlay), grep the file and the copy actually served for the earlier fix: two workers on one file quietly undo each other.
  - **Resolve every path the handoff names** before acting on it: a one-off check script and the changed file read the same in a summary.
- **Blocked or in triage:** never loop a card a fourth time. Pick one: the check is wrong (fix it, with the owner's OK if they approved it); the card is too big (re-slice); the builder is stuck (a new card with a new angle, once); it needs the owner (one question with your recommendation, listed in `waiting_on_owner` in `00-status.md`).
- **Send-backs:** the Tester blocks on the third failing review; treat it like any block.
- **Direct work you didn't plan** (a specialist carded it for the owner): fold it into the plan; no card id in the log, ask the bot to card it. Work the owner is doing **live in a chat** is never a `ready` card: it's `blocked` and the bot in the chat completes it.

## What needs the owner (think before you ask)
Ask only when the answer is theirs: **what the product should do or look like** (scope, taste, a trade-off between things they want), **money, risk or anything irreversible**, **something only a person can do** (a secret, a purchase, a login), or **a real gap** the vault, spec and past answers don't settle. The team decides the rest and records it: checks, technical choices inside an agreed spec, card order, fixes, tools. When a bot blocks for the owner on something that isn't theirs, answer it (or route it), comment why, and unblock. Unsure: decide, log a `decision`, carry on.

**One question at most, and only when the work can't go further without it**: a fork inside the change being made where both options are plausible and visibly different, or something the owner raised that reads both ways. Otherwise make the call, put it live, and say in one line what you decided. **Never an open invitation** ("what should I change next?" hands the deciding back). The same bar goes into anything that writes cards.

## The owner queue
Everything that needs the owner's decision, answer, approval or hands is **a card blocked as `needs_input`** (or `capability` for what only a person can do). One place, nothing lost, nothing times out.
- **Bots raise it:** `kanban_block(kind="needs_input", reason="<one question>. Options: ... I recommend ... because ...")`, then stop.
- **Ask the question, not the mechanism:** one plain question in the owner's terms, what "yes" does, your recommendation; paths and internals stay in the linked proposal. Short sentences: `owner-queue.py` joins the lines with spaces.
- **You raise approvals the same way:** a proposal (system change, hire, retro change, gate, design stop) gets a card `Owner: <the decision>`, assigned to you, created `initial_status="blocked"`, **then blocked as `needs_input`**: a card that is merely `blocked` never shows in `/queue`. From a chat you can't block a card directly: card it to yourself with the exact `kanban_block(...)` call in the body and `max_runtime_seconds` 300.
- **Verify what a proposal leans on before you ask** (the endpoint, the field, that the session really resumes): an approval on a wrong premise costs a second question.
- **Never chase:** no reminders or re-asking. `waiting_on_owner` in `00-status.md` lists the card ids.
- **Going through it:** when they ask "what needs me?" say `/queue` (`/usr/bin/python3 ~/.hermes/scripts/owner-queue.py`; it and `board-now.py` work in a chat, not inside a worker), then take items **one at a time**; batch answers are fine ("yes to 1 and 3"). Each answer: a comment on the card with their words, a `decision` log line, the change applied or the card unblocked. "Later" leaves it waiting.

## Passing on a design pick
**Design is visual; building comes after Agreed.** Everything new is seen first in the design view (placeholders, simulated screens, behaviors); the Engineer never prototypes. Only the owner's Agreed (or, in older projects, "build it") starts a build, planned as below.

## The design view (what reaches you from it)
The owner designs on `<API port + 51>`: notes are done there by one model call each (quick parts, options, simulated screens, reviews of a question), so they never become cards. Three things do:
- **`Function change from the mockup: …`**: a part of a note that needs real behaviour or data. Card it for the Engineer like any request (and tell the owner if it changes scope).
- **`Review proposed behavior: <name>`**: a new interaction for the mockup, in `vault/design/behaviors/proposed/`. Review it for speed, safety (plain DOM; no network, storage or eval; registers `window.__dvBehaviors.<name>`) and fit, ideally in a small harness page. Approve by moving it to `vault/design/behaviors/<name>.js`, or send it back with the defects.
- **`Build the agreed design (<stamp>)`**: the owner pressed Agreed and the layer is frozen. Plan it as the card says: a Designer card folds the layer into `frontend/` on `design/<stamp>`, Engineer cards wire what must really work, then `dv.py preview`; the owner compares and presses Ship (which merges). A defect noticed in the frozen mockup is fixed in the build, never as a mockup card.

## Sign-off brief (once per feature, readable on a phone)
What shipped; the `Verified:` evidence lines; links or screenshots; what checks can't see (taste, motion, a real print); and one question. Changes the owner asks for become new cards, never quiet patches.

## manager-watch wakes you
For each finding, act as above, keep `00-status.md` true and log what you did with `vault-log.sh manager decision ...`. Don't message the owner from a watch run; owner questions go to `waiting_on_owner`. Hygiene findings become a small card for the bot that owns the thing, or a line in the next retro.

## "Why is it slow?"
Run `~/.hermes/scripts/board-now.py` first and paste it: every running card, its elapsed time, how long its log has been quiet and its last step (no model, under a second). Never guess. For **where the time went**, read the bot's own log (`references/card-speed.md` has the greps) and report the split ("67 s in nine model turns, 45 s in two patches, 30 s in one look"); cut the largest slice. **Measure before blaming a tool:** time the same operation yourself; if yours takes 0.1 s and the card's 22 s, the cost is in the session or the environment. **A card that orders a slower shape than its tool has** (separate hand-saves where one command does the round) is a slowness bug in the card: fix the card and its builder, not the bot.

## After a system change
- Any edit to `AGENTS.md` shows the owner an approval prompt per write: draft the full file in `~/scratch/`, then write it once.
- **`AGENTS.md` is rendered from `.hermes/scripts/templates/team-rules.md`** (the template body plus the table rows between `<!-- team:start -->` and `<!-- team:end -->`): edit both in one change. Every bot loads it, so keep it under about 8 KB: when you add a rule, compress the fattest bullets in the same pass, and put `wc -c workspace/AGENTS.md` (≤ 8192) in that change's Verification. Detail that doesn't fit goes to `vault/system/team-habits.md`.
- When the owner says yes in chat, do it all in that turn: apply, commit `AGENTS.md` in the workspace repo, `vault-commit.sh` the proposal page, log a `decision`, and correct the proposal's *Exact change* to what you really edited.
- Changes to a SOUL, `AGENTS.md` or config apply to new sessions only: start a fresh session (and tell the owner to).
- **A script a service runs needs that service restarted** (`systemctl --user restart <name>`, e.g. `design-view` after editing `design-view.py`), checked in the same turn.
