---
title: Owner profile
type: system
status: active
owner: manager
updated: {{DATE}}
summary: How {{OWNER}} works and wants to be worked with; its seed block becomes each new bot's USER.md.
tags: [system, owner]
---

# Owner profile: {{OWNER}}

The one place where {{OWNER}}'s standing working rules live. Every bot follows them. The Manager keeps this page true; a change is a proposal {{OWNER}} approves (`system/changes/`). Project-specific decisions belong in `product/`, not here.

## Standing rules
- One question at a time, each with a recommended answer. No lists of questions.
- Short and plain. Lead with the answer or the decision needed.
- Verify by running, never assume. Say what you ran.
- No secrets anywhere: never print, copy or commit `.env`, tokens or keys.
- Nothing irreversible, costly or outside the project without an explicit OK.
- Small steps, each with a stop for a yes before big builds.
- Keep docs and tasks updated as work proceeds.

## Seed for new bots
`hire.sh` copies the text between the markers into each new bot's `USER.md` (at most 1,375 characters; keep it well under). Keep it to facts about {{OWNER}} that every bot needs from day one.

<!-- user-seed:start -->
{{OWNER}} is the owner. Wants one question at a time, each with a recommendation. Short, plain messages; answer or decision first. Verify by running and say what was run; never assume. No secrets in any output or file. Nothing irreversible or costly without an explicit OK from {{OWNER}}. Prefers small steps, with a stop for a yes before big builds.
<!-- user-seed:end -->
