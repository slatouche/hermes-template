---
name: roadmap
description: "Owner goals to roadmap: shape, slice, side tracks."
version: 1.0.0
author: Project template
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [roadmap, epics, storyboard, slices, side-tracks, planning]
    related_skills: [intake-interview, work-planning]
---

# Roadmap

Use when the owner brings bigger goals ("these are the things I want"), when a feature ships and the next one should start, or when the owner asks "what's next?". The aim: the owner can pour in ideas at any time, nothing gets lost, only a little is in progress at once, and each feature arrives in small pieces they can see and steer.

## The roadmap page
`product/roadmap.md`, one table, in the owner's order of priority:

| Feature | Why (the owner's words) | Status | Next step | Links |
|---|---|---|---|---|

Status is one of: `idea` → `shaping` → `ready` → `building` → `shipped`, or `parked` (with why). **At most one feature `shaping` and one `building` at a time**; everything else waits in order. A vague wish goes to `product/ideas.md` until it's a feature.

## When the owner brings a list
1. Write each goal as a row (`idea`), in their words. Don't shape anything yet.
2. One question: "Which first?" with your recommendation (the one that unblocks others, or the smallest that's useful on its own).
3. Split out **side tracks**: work that serves the product but isn't part of it (reverse-engineering another app, pulling a dataset, an experiment). They get their own row marked `side track` and the rules below.

## Shaping a feature (the one at the top)
1. **Interview just this feature** (`intake-interview`, about 3-8 questions): who uses it, what they do step by step, what "done" means, what's out. Write `product/features/<feature>.md`.
2. **Research what's unknown** (a Researcher card: prior art, assets, licences, formats). Only what the next decision needs.
3. **Storyboard** (a Designer card): the user's journey as 4-8 rough frames, shown on a demo slot (`demo.sh`). The owner marks it up; that's the cheapest place to change their mind.
4. **Slices:** cut the feature into thin end-to-end increments, each one usable on its own and visible on the mockup (`<API port + 51>`; slice 1 is the smallest thing worth trying: often the happy path with one option). Write them in the feature page; the owner approves the list once.
5. Status → `ready`, then `building` when its first slice is carded (and nothing else is `building`).

## Building, slice by slice
- Each slice is the normal chain (`work-planning`): design step if needed → build → review → land → running on the app, and on the mockup after `mockup.sh refresh`.
- After each slice: a sign-off brief and the mockup link. The owner tries it and marks it up; their notes and any new ideas reshape the **remaining** slices (update the feature page; never patch quietly).
- When the slices are done: status `shipped`, a one-line entry in the log, and the next feature in order starts shaping.

## Side tracks (ad-hoc work outside the product)
- **Its own place:** a folder `~/side/<track>/` (outside `workspace/` and git; downloads, scripts, scratch), findings in `research/<track>/`, and its own board (`hermes kanban boards create side-<track>`) so its cards don't crowd the product's.
- **Bounded:** write the goal, the exit condition ("we have the frame assets and a spec of the frame system") and a cap (cards or days) in the roadmap row before starting.
- **Runs as a loop, not one big card:**
  1. **Recon** (one Researcher card, about 30 minutes, `deep-research` §0): the target, its source code and licence, forks and similar projects, the ways in (public repo, the running app in a browser, files it loads, exports), and what's already in the vault. It ends with a short brief: what we know, the open questions, and a recommended plan of probes.
  2. **Plan:** you turn the brief into small probe cards on the side board, each one question with a yes/no or a measurement as its Verification ("can we load a pack's frame images from the public repo?", "does using the app in a browser expose the art at full size?"). Show the owner the plan only when it costs money, needs their hands, or goes somewhere they'd care about; otherwise just start it.
  3. **Probe:** the Researcher works the cards like a person would: opens the app in the browser, uses the features, watches what loads, saves and exports, and tries the cheapest route first. Results go to `research/<track>/`.
  4. **Decide:** a findings page with a recommendation and what it means for the product, then the product work it implies as rows or slices on the roadmap, and one `Owner:` card with the decision that's theirs (adopt, build our own, park). Not a pile of specs to read.
- **Ends with a clean-up card:** keep the findings (research pages), move anything the product needs into `workspace/` through a proper card (with source and licence noted), then delete `~/side/<track>/`, archive the board, and mark the row `shipped` or `parked`. `manager-watch` flags a side track past its cap.

## Keep it true
- Re-read the roadmap at session start when anything is `shaping` or `building`; update it the same turn things change.
- The retro checks it: stalled rows, too much in progress, side tracks that never ended.
- Show the owner the roadmap (the table, nothing else) whenever they ask "what's next?" or a feature ships.
