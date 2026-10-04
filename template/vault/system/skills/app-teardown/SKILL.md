---
name: app-teardown
description: "Study an existing app and write feature specs."
version: 1.0.0
author: Project template (generalised from the TCG Proxy bot's browser-ui-walkthrough)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [research, teardown, browser, specs, competitor, reverse-engineering]
    related_skills: []
---

# App teardown

Use when a card asks you to study an existing app (a website or tool) so the owner can pick which of its features to build. The output is specs in our own words plus a catalogue the owner picks from, never copied code or assets.

## The chain (the Manager cards each step; one card per area keeps context small)
1. **Inventory.** Tour every screen, panel, menu and option list in the browser. Keep a coverage list in `research/<app>/coverage.md` (area, sub-items, status: to do / done / blocked) and tick items off as you go. Screenshots of each screen. Output: the feature tree.
2. **Probe each area** (one card each). Try normal and edge inputs; measure outputs (sizes, resolutions, timings, text fitting, layers) with the browser's DOM and computed styles, not by eye. Output: behaviour notes with evidence.
3. **How it works.** Saved and exported files, the data model, asset declarations, network calls, the public code if there is any. Mark everything **observed** or **inferred**.
4. **Feature specs:** one page per feature in `research/<app>/<feature>.md`, using the template below.
5. **The catalogue:** `research/<app>/catalogue.md`, one row per feature: value to the owner, rough effort, and an empty **pick / later / skip** column. The Manager brings it to the owner.
6. The owner's picks become build cards (Designer and Architect first where needed).

## Spec page template
```
# <Feature>
What the user does: <steps>
Options and inputs: <list, with limits>
Output: <what comes out, measured>
Edge cases: <what happens with empty, huge, odd input>
How it works: <mechanism; each line marked observed or inferred>
Evidence: <screenshots, files, links>
Value to the owner: <one line>      Rough effort: <S / M / L, with why>
```

## Rules
- Resume, don't repeat: read `coverage.md` and your last notes before each step.
- Write notes after every step, not at the end.
- No getting around logins or paywalls. Bulk downloads of public files only when the owner has allowed it for this app: rate-limited, resumable, and from the public code repo if it already holds them. Record what was downloaded and from where.
- Specs are in your own words. Don't copy the app's code, text or art into our product; facts and measurements are fine.
- One area per card. If an area turns out big, finish what's carded and propose the split.

## Done when
- [ ] `coverage.md` has no "to do" left for the carded area.
- [ ] Every spec has evidence, observed/inferred marks, value and effort.
- [ ] The catalogue lists every spec, ready for the owner's picks.
