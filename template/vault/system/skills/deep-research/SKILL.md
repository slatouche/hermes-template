---
name: deep-research
description: "Research online: plan, search wide, verify every claim."
version: 1.0.0
author: Project template
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [research, web, search, citations, verification, sources]
    related_skills: [app-teardown]
---

# Deep research

Use for any question that needs the web: prior art, how something works, prices, licences, tools to adopt, facts the owner will act on. The danger in AI research isn't missing links, it's confident claims the cited page doesn't support (studies of deep-research agents find many citations don't back their claim). So every claim here carries the exact sentence it rests on, and a script checks those sentences against the live pages.

## 0. Recon (when the question is "how could we get or copy X?")
Before going deep, map the ground in one short pass and hand back:
- **The target:** what it is, who runs it, where its code lives (repo, licence, last commit), how it's served.
- **The neighbours:** forks, ports, similar projects and tools that already solved part of it (search `categories=it` for the name plus "fork", "clone", "alternative", "assets", "api"). A maintained fork or an existing dataset often saves the whole job.
- **The ways in, cheapest first:** a public repo or dataset, the app's own export, files the app loads (watch the browser's network log), an API, then scraping as the last resort.
- **What's already known:** the vault and `raw/` first, so nothing is redone.
- **The brief** (`research/<track>/recon.md`): the answer so far in 3 lines, the open questions, and a recommended plan of probes (each one question you can answer with a yes/no or a measurement). Stop there: the Manager plans the next cards.

## 1. Plan (before any search)
- Restate the question and what decision it feeds. Split it into 3-6 sub-questions. Write them at the top of `research/<topic>.md`.
- For each, note what would count as a good source: the official docs, the code itself, a dated release note, a measurement, a primary paper. Forums and blog posts are leads, not proof.

## 2. Search wide, then narrow
- Several phrasings per sub-question; the exact names of things; the error text; the year. Look in different places:
  - general web: `web_search` (it uses the host's SearXNG: Google and Bing together);
  - code and Q&A: `curl -s "http://127.0.0.1:8888/search?q=<terms>&categories=it&format=json"` (GitHub, Stack Overflow, MDN);
  - papers: the same with `categories=science` (arXiv, Semantic Scholar, Google Scholar).
- Prefer primary sources and recent dates. Note the date of every source; say when something may have changed since.
- Sub-agents (`delegate_task`) for independent sub-questions when there are several: each returns its claims table, never just prose.

## 3. Read whole pages
- `web_extract` for the page text; the browser tool for pages built by JavaScript, behind cookie walls or with images that matter (screenshots, then vision). Read the part that answers the sub-question, not just the snippet.
- Never claim from a search snippet alone.

## 4. Keep a claims table
In the research page, as you go:

| # | Claim | Source | Quote |
|---|---|---|---|
| 1 | <one fact, in your words> | <URL> | "<a short exact sentence copied from that page>" |

One claim per row, the quote copied exactly (not paraphrased). Mark inferred claims "inferred" in the Claim cell and give the rows they rest on instead of a quote.

## 5. Verify
- Run `/usr/bin/python3 ~/.hermes/scripts/cite-check.py vault/research/<topic>.md`. Fix every NOT FOUND (wrong quote, wrong page, or a claim the source doesn't make: drop it). COULDN'T FETCH: check with the browser tool and add "(checked in the browser)".
- Anything the owner will spend money, time or a decision on needs **two independent sources** (not two pages copying each other).
- Disagreeing sources: keep both, say which you trust and why.

## 6. Write it up (answer first)
At the top of the page: the answer in 2-4 lines, your recommendation, and what's still unsure. Then the findings by sub-question, the claims table, and the sources with dates. In the card handoff: `Verified: cite-check → N claims, 0 to fix`.

## Pitfalls
- Searching once and writing up: the first results are often SEO pages and stale posts.
- Treating a GitHub README's claims as measured facts: say "the README says".
- Long copied passages: quote one sentence, summarise the rest in your words.
- No logins, no paywalls, no getting around blocks. Bulk downloads only when the owner allowed them, and politely.
