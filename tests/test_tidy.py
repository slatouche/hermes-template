#!/usr/bin/python3
"""Checks for template/scripts/tidy.py (the nightly tidy: slices, the meaning map, apply and rollback), no model.

  python3 tests/test_tidy.py      (a temporary project home with a throwaway git repo; nothing else touched)
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent / "template"
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  ({detail})"))
    if not ok:
        failures.append(name)


def main():
    home = pathlib.Path(tempfile.mkdtemp(prefix="tidy-"))
    env = dict(os.environ, PROJECT_HOME=str(home))

    def w(p, text):
        (home / p).parent.mkdir(parents=True, exist_ok=True)
        (home / p).write_text(text, encoding="utf-8")

    def r(p):
        return (home / p).read_text(encoding="utf-8")

    def tidy(*a):
        x = subprocess.run([sys.executable, str(ROOT / "scripts" / "tidy.py"), *a], capture_output=True, text=True, env=env)
        return x.returncode, x.stdout + x.stderr

    agents = ("# t: agent guide\n\n## This project\nTCG-style app: decks in ProxyDecks/.\n\n## Cards\n- **Rule A.** Do the card.\n- **Rule B.** Never pkill -f.\n"
              "- **Rule A again.** Do only the card.\n\n<!-- team:start -->\n| Bot | Owns | Ask |\n|---|---|---|\n"
              "| Manager | front door | anything |\n| Engineer | code | building |\n<!-- team:end -->\n")
    w("workspace/AGENTS.md", agents)
    subprocess.run("git init -q -b main && git config user.email t@t && git config user.name t && git add -A && git commit -qm i",
                   shell=True, cwd=home / "workspace", check=True)
    w("vault/system/team-habits.md", "---\ntitle: habits\n---\n# Team habits\n- Memory holds facts.\n")
    w("vault/system/lessons.md", "# Lessons\n")
    w("vault/system/overview.md", "# Overview\n- one\n")
    w(".hermes/scripts/templates/team-rules.md", agents.replace("| Engineer | code | building |\n", ""))
    w(".hermes/scripts/vault-log.sh", '#!/bin/bash\necho "$*" >> "$PROJECT_HOME/log.txt"\n')
    w(".hermes/scripts/vault-commit.sh", '#!/bin/bash\necho "$*" >> "$PROJECT_HOME/commits.txt"\n')
    w(".hermes/profiles/manager/SOUL.md", "# Manager\n- front door\n")
    w(".hermes/profiles/engineer/SOUL.md", "# Engineer\n- builds\n")
    w(".hermes/profiles/engineer/memories/MEMORY.md", "The owner likes short answers.\n")
    w("vault/system/roles/engineer.md", "---\nrole: engineer\n---\n# Engineer\n- builds\n")

    code, out = tidy("slices", "--json")
    sl = json.loads(out)
    check("slices: team rules, each bot, the vault's system pages", set(sl) == {"team-rules", "bot:engineer", "bot:manager", "vault-system"}, sl)
    check("slices: a bot with a role page is tidied through it, never its SOUL",
          "vault/system/roles/engineer.md" in sl["bot:engineer"] and not any(f.endswith("SOUL.md") for f in sl["bot:engineer"])
          and ".hermes/profiles/manager/SOUL.md" in sl["bot:manager"], sl)

    code, out = tidy("new", "team-rules")
    st = json.loads(out)
    stage, prop = home / st["stage"], st["proposal"]
    check("new: a copy of each file to edit, the map's skeleton, the proposal", (stage / "new" / "workspace/AGENTS.md.staged").exists()
          and "- U3 ?" in (stage / "meaning-map.md").read_text() and (home / prop).exists(), out)
    code, out = tidy("check", prop)
    check("check: nothing changed is not a tidy", code == 1 and "nothing changed" in out, out)
    check("new: instruction files are staged under another name (a bot may draft one, not write one)",
          (stage / "new" / "workspace/AGENTS.md.staged").exists() and not (stage / "new" / "workspace/AGENTS.md").exists())

    # the tidy: merge Rule A's duplicate, move a line to team-habits
    (stage / "new" / "workspace/AGENTS.md.staged").write_text(agents.replace("- **Rule A again.** Do only the card.\n", "")
                                                       .replace("- **Rule A.** Do the card.", "- **Rule A.** Do the card, and only it."))
    code, out = tidy("add", st["stage"], "vault/system/team-habits.md")
    (stage / "new" / "vault/system/team-habits.md").write_text(r("vault/system/team-habits.md") + "- Never pkill -f: it can match your own worker.\n")
    (stage / "new" / "workspace/AGENTS.md.staged").write_text((stage / "new" / "workspace/AGENTS.md.staged").read_text().replace("- **Rule B.** Never pkill -f.\n", ""))
    code, out = tidy("check", prop)
    check("check: an unmapped unit fails, named", code == 1 and "units not accounted for: U1" in out, out)
    mp = (stage / "meaning-map.md").read_text()
    mp = mp.replace("- U1 ?", "- U1 rewritten").replace("- U2 ?", "- U2 moved: `vault/system/team-habits.md`") \
           .replace("- U3 ?", "- U3 merged: U1").replace("- U4 ?", "- U4 kept").replace("- U5 ?", "- U5 kept") \
           .replace("- U6 ?", "- U6 removed: x").replace("- U7 ?", "- U7 kept")
    (stage / "meaning-map.md").write_text(mp)
    code, out = tidy("check", prop)
    check("check: removed needs a reason", code == 1 and "removed needs its reason" in out, out)
    mp = mp.replace("- U6 removed: x", "- U6 kept")
    (stage / "meaning-map.md").write_text(mp)
    code, out = tidy("check", prop)
    check("check: the team rules changed, so the eval verdict is required", code == 1 and "Eval verdict" in out, out)
    (home / prop).write_text(r(prop).replace("Eval verdict: <no worse | better | worse: then don't propose it>", "Eval verdict: no worse")
                             .replace("<one line per change", "Merged rule A's duplicate; moved the pkill reason to team-habits (-60 bytes).\n<x"))
    code, out = tidy("check", prop)
    check("check: everything mapped, verdict recorded -> pass", code == 0 and "PASS" in out, out)
    w("workspace/AGENTS.md", agents + "\n- someone's new rule\n")
    code, out = tidy("check", prop)
    check("check: a live file changed since staging -> stale", code == 1 and "stale" in out, out)
    w("workspace/AGENTS.md", agents)

    code, out = tidy("apply", prop)
    check("apply: an instruction file waits for the owner (Hermes guards them)", code == 3 and "--owner-present" in out
          and r("workspace/AGENTS.md") == agents, out)
    code, out = tidy("apply", prop, "--owner-present")
    new_agents = r("workspace/AGENTS.md")
    check("apply: the new files are in place", code == 0 and "Rule A again" not in new_agents and "Never pkill -f: it can match" in r("vault/system/team-habits.md"), out)
    tr = r(".hermes/scripts/templates/team-rules.md")
    check("apply: the template copy follows AGENTS.md but keeps its own team table", "Rule A again" not in tr and "| Engineer |" not in tr, tr)
    check("apply: the template copy never takes the project's own section", "This project" not in tr and "ProxyDecks" not in tr, tr)
    check("apply: AGENTS.md committed, vault files checkpointed, logged, noted", "Tidy team-rules" in subprocess.run(
        ["git", "-C", str(home / "workspace"), "log", "-1", "--format=%s"], capture_output=True, text=True).stdout
          and "team-habits" in r("commits.txt") and "rollback" in r("log.txt") and "Merged rule A" in r("vault/system/optimiser/applied.md"))
    check("apply: the proposal says applied", "status: applied" in r(prop))
    check("apply: applied.md is a vault page (the standard header)", r("vault/system/optimiser/applied.md").startswith("---\n")
          and "\nsummary:" in r("vault/system/optimiser/applied.md"))
    code, out = tidy("rollback", prop)
    check("rollback: every file as it was", code == 0 and r("workspace/AGENTS.md") == agents and "Never pkill -f: it can" not in r("vault/system/team-habits.md"), out)

    # a bot: its role page changes, its SOUL is regenerated from it; the SOUL itself can't be the thing edited
    code, out = tidy("new", "bot:engineer")
    st = json.loads(out)
    stage, prop = home / st["stage"], st["proposal"]
    (stage / "new" / "vault/system/roles/engineer.md").write_text("---\nrole: engineer\n---\n# Engineer\n- builds, with tests\n")
    (stage / "meaning-map.md").write_text((stage / "meaning-map.md").read_text().replace("- U1 ?", "- U1 rewritten", 1))
    tidy("add", st["stage"], ".hermes/profiles/engineer/SOUL.md")
    (stage / "new" / ".hermes/profiles/engineer/SOUL.md.staged").write_text("# Engineer\n- hand edit\n")
    code, out = tidy("check", prop)
    check("check: a SOUL is changed through its role page, not by hand", code == 1 and "change its source" in out, out)
    shutil.copy(stage / "old" / ".hermes/profiles/engineer/SOUL.md.staged", stage / "new" / ".hermes/profiles/engineer/SOUL.md.staged")
    (home / prop).write_text(r(prop).replace("Eval verdict: <no worse | better | worse: then don't propose it>", "Eval verdict: better"))
    code, out = tidy("apply", prop, "--owner-present")
    check("apply: the SOUL is regenerated from the new role page", code == 0 and r(".hermes/profiles/engineer/SOUL.md") == "# Engineer\n- builds, with tests\n", out)

    code, out = tidy("new", "vault-system")
    st = json.loads(out)
    stage, prop = home / st["stage"], st["proposal"]
    (stage / "new" / "vault/system/overview.md").write_text("# Overview\n- one, said plainly\n")
    (stage / "meaning-map.md").write_text((stage / "meaning-map.md").read_text().replace("- U1 ?", "- U1 rewritten"))
    code, out = tidy("apply", prop)
    check("apply: a tidy of vault pages needs no owner (and no eval)", code == 0 and "said plainly" in r("vault/system/overview.md"), out)

    shutil.rmtree(home, ignore_errors=True)
    print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
