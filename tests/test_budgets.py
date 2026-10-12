#!/usr/bin/python3
"""Size budgets for what every bot loads each session, so a project's own additions always fit under the hard limits.

  python3 tests/test_budgets.py

The hard limits (manager-watch flags them in a project): workspace/AGENTS.md 8 KB, a SOUL 10 KB. The template's own
part must leave room for what each project adds: AGENTS.md gets a project section and a team-table row per bot,
the Manager's SOUL gets the project's wording. A new rule in the template has to fit the budget, so it replaces or
shortens something; detail goes to vault/system/team-habits.md or a skill.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "template"
BUDGETS = {                                     # bytes for the template's part
    "workspace/AGENTS.md": 6500,               # 8192 hard: leaves ~1.7 KB for the project section and team rows
    "manager/SOUL.md": 8500,                   # 10000 hard: leaves 1.5 KB for the project's own wording
}
ROLE_SOUL = 8000                               # a hired bot's SOUL (role page body, or its working file)
ROW_MAX = 200                                  # one team-table row (hire.sh writes it from the role's owns/ask_when)
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))
    if not ok:
        failures.append(name)


for rel, cap in BUDGETS.items():
    n = len((ROOT / rel).read_bytes())
    check(f"{rel} within its budget ({n}/{cap} bytes)", n <= cap, f"{n - cap} bytes over: shorten or move detail out")

roles = ROOT / "vault" / "system" / "roles"
for f in sorted(roles.glob("*.md")):
    if f.name.startswith("_") or f.name.endswith(".working.md"):
        continue
    src = f.with_name(f.stem + ".working.md") if f.with_name(f.stem + ".working.md").exists() else f
    body = re.sub(r"\A---\n.*?\n---\n", "", src.read_text(encoding="utf-8"), count=1, flags=re.S)
    n = len(body.encode())
    check(f"{f.stem}'s SOUL within {ROLE_SOUL} bytes ({n})", n <= ROLE_SOUL, f"{n - ROLE_SOUL} over")
    fm = f.read_text(encoding="utf-8")
    disp = re.search(r'^display:\s*"?(.*?)"?\s*$', fm, re.M)
    owns = re.search(r'^owns:\s*"?(.*?)"?\s*$', fm, re.M)
    ask = re.search(r'^ask_when:\s*"?(.*?)"?\s*$', fm, re.M)
    if disp and owns and ask:
        row = f"| {disp.group(1)} | {owns.group(1)} | {ask.group(1)} |"
        check(f"{f.stem}'s team row within {ROW_MAX} bytes ({len(row.encode())})", len(row.encode()) <= ROW_MAX,
              "shorten owns / ask_when")

print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
