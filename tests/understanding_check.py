#!/usr/bin/env python3
"""understanding_check.py: does the design view work out WHAT the owner means? A live check, not a unit test: it sends
notes with known answers to a running design view's dry run (POST /dv/dry-run: nothing changes) and scores each:
RIGHT, WRONG, or ASK (it saw the note wasn't clear and would ask the owner; ASK+ when the right thing is among the
choices it offers). It costs real model calls (about 4 per note).

  python3 tests/understanding_check.py [runs] [--url http://127.0.0.1:<port>] [--case N ...] [--old]

--old runs the plan alone (no working out first), for comparison. The cases below are TCG Proxy's deck page as it was
on 2026-10-14, at 1440 px: each names its marks by selector or by a drawn box, so they hold only while the page still
has those things. When the design moves on, replace them with notes from the current page (the history of the
design view's notes, vault/design/layer/history.jsonl, is a good source).

Tested 2026-10-14: plan alone about 2 in 3 right; worked out first 44 of 45 right, 1 asked, none wrong.
"""
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROUTE = "#/deck/You've%20Got%20To%20Be%20Cidding%20Me"
VIEW = {"route": ROUTE, "w": 1440, "h": 909}
area = lambda x, y, w, h: {"kind": "area", "sel": "#app", "rect": {"x": x, "y": y, "w": w, "h": h}}
el = lambda s: {"sel": s}
LINES_RIGHT, LINES_WRONG = r"vertical|divider|separator|double (border|line)|two (borders|lines)", r"horizontal|top|bottom|under|wrap|row"
# (note, marks, right if the answer matches, wrong if it matches)
CASES = {
    2: ("no the issue is that there are 2 lines between the items in this header bar. on the left there is just 1, while on the right there are 2",
        [el("div.vgroup:nth-of-type(2)"), el("div.viewbar > details.panel-fold")], LINES_RIGHT, LINES_WRONG),
    3: ("the highlighted one is way too bright, tone it down", [el("#deck-tabs")], r"deck view|active", r"proxy view"),
    5: ("the number box under the card looks cramped", [el("div.card-group:nth-of-type(2)")],
        r"qty|quantity|stepper|counter|[−-] ?1 ?\+|minus|number box|count", r"^$"),
    7: ("the dots are distracting", [el("div.rail-scroll > details.panel-fold:nth-of-type(1)")], r"dot|handle|grip|drag", r"^$"),
    8: ("the line under it is too thick", [el("#topbar-deck")], r"underline|line under|bottom border|border under|cyan|teal|accent", r"^$"),
    9: ("these should line up with the right edge of the buttons above", [area(1285, 150, 30, 230)],
        r"count|number|digit|\b29\b|\b12\b|\b23\b", r"^$"),
}


def one(url, old, c):
    note, marks, right, wrong = CASES[c]
    body = {"note": note, "marks": marks, "route": ROUTE, "view": VIEW, "identify": not old}
    t = time.monotonic()
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request(url + "/dv/dry-run", json.dumps(body).encode(),
                                                                     {"Content-Type": "application/json"}), timeout=180))
    except Exception as e:
        return c, "ERROR", str(e), 0
    seen, plan = r.get("seen") or "", " | ".join(p["text"] for p in r.get("parts") or [])
    if seen.startswith("asked:"):
        status = "ASK+" if any(re.search(right, x, re.I) and not re.search(wrong, x, re.I) for x in seen[6:].split("|")) else "ASK-"
    else:
        said = seen.split(":")[0] if (seen and not old) else plan       # the short name of the thing, or the plan's line
        status = "RIGHT" if re.search(right, said, re.I) and not re.search(wrong, said, re.I) else "WRONG"
    return c, status, (seen[:300] + " || " if seen else "") + plan[:200], time.monotonic() - t


def main():
    args = sys.argv[1:]
    url = args[args.index("--url") + 1] if "--url" in args else "http://127.0.0.1:10151"
    only = {int(x) for x in re.findall(r"\d+", " ".join(args[args.index("--case") + 1:]))} if "--case" in args else set()
    runs = int(args[0]) if args and args[0].isdigit() else 2
    old = "--old" in args
    jobs = [c for c in CASES if not only or c in only for _ in range(runs)]
    res = []
    with ThreadPoolExecutor(4) as ex:
        for c, st, said, s in ex.map(lambda c: one(url, old, c), jobs):
            res.append((c, st, s))
            print(f"{st:5} case {c} {s:4.1f}s  {said}", flush=True)
    count = lambda st: sum(1 for r in res if r[1] == st)
    print(f"\n{'plan alone' if old else 'worked out first'}: right {count('RIGHT')} · asked {count('ASK+')} "
          f"(+{count('ASK-')} without the right choice) · wrong {count('WRONG')} · errors {count('ERROR')} of {len(res)} "
          f"· avg {sum(r[2] for r in res) / max(1, len(res)):.1f}s")
    return 1 if count("WRONG") or count("ERROR") else 0


if __name__ == "__main__":
    sys.exit(main())
