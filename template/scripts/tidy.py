#!/usr/bin/python3
"""tidy.py: the nightly tidy of what the bots load (rules, SOULs, skills, memory, vault pages), made safe by script.

The Optimiser tidies one slice a night: it rewrites, moves and merges lines so each thing is said once, in the place
it belongs (its `optimise` skill, references/placement.md), and nothing it meant is lost. This script holds the
parts that must be exact:

  tidy.py slices [--json]            the slices and their files (what the nightly rotation walks through)
  tidy.py new <slice>                stage tonight's tidy: ~/scratch/tidy/<date>-<slice>/ with a copy of each file
                                     to edit (new/<path>), the meaning map's skeleton (every unit of every file) and
                                     the proposal page's skeleton in vault/system/changes/
  tidy.py add <stage> <file>         stage one more file (where something moves to), with its map section
  tidy.py units <file>               a file's units: the lines a meaning map must account for
  tidy.py check <proposal>           every changed file's every unit is mapped (kept, rewritten, moved, merged or
                                     removed with a reason); moved/merged destinations exist; the live files haven't
                                     changed since staging; a SOUL is changed through its source; the eval verdict
                                     is recorded for anything a bot loads
  tidy.py apply <proposal> [--owner-present]
                                     check, then put the new files in place (backups kept), regenerate SOULs from
                                     their sources, commit, log, and add a line to vault/system/optimiser/applied.md.
                                     A tidy that touches an instruction file (the team rules or a bot's SOUL, or a SOUL's
                                     role page) is applied only with --owner-present: Hermes lets those change only with
                                     a person there to approve, so it's applied in a chat with the owner after their yes
  tidy.py rollback <proposal>        put every file back as it was before apply

A meaning map (meaning-map.md in the staging folder), per changed file:
  ## workspace/AGENTS.md
  - U3 kept | rewritten | moved: `vault/system/team-habits.md` | merged: U7 | removed: <why, in a sentence>
"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

HOME = pathlib.Path(os.environ.get("PROJECT_HOME") or pathlib.Path.home())
H = HOME / ".hermes"
STAGE = HOME / "scratch" / "tidy"
KINDS = ("kept", "rewritten", "moved", "merged", "removed")
APPLIED_HEAD = """---
title: "Tidies applied"
type: system
status: active
owner: optimiser
updated: {day}
summary: "Each Optimiser tidy the Manager applied: when, what, and the command that rolls it back (written by tidy.py)."
tags: [system, tidy]
---
# Tidies applied

"""
PROTECTED = {"AGENTS.md", "SOUL.md", "CLAUDE.md", "HERMES.md", ".hermes.md", ".cursorrules"}   # Hermes guards these
LOADED = re.compile(r"^(workspace/AGENTS\.md|\.hermes/profiles/[^/]+/(SOUL\.md|memories/(MEMORY|USER)\.md)|vault/system/roles/[^/]+\.md)$")


def st(f):
    """Where a file sits in the staging folder: an instruction file under another name (a bot may draft one, never
    write one), so the Optimiser can edit its copy."""
    return f + ".staged" if pathlib.PurePosixPath(f).name in PROTECTED else f


def touches_instructions(files):
    return any(pathlib.PurePosixPath(f).name in PROTECTED or soul_source_of(f) for f in files)


def soul_source_of(f):
    """True when f is the role page some bot's SOUL is generated from."""
    m = re.match(r"vault/system/roles/([^/]+?)(\.working)?\.md$", f)
    return bool(m and (H / "profiles" / m.group(1) / "SOUL.md").exists()
                and (m.group(2) or not (HOME / "vault" / "system" / "roles" / f"{m.group(1)}.working.md").exists()))


def rel(p):
    return str(pathlib.Path(p).resolve().relative_to(HOME.resolve())).replace("\\", "/")


def sha(p):
    p = HOME / p
    return hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else None


def slices():
    """slice -> files (paths from the project home). A bot's slice holds its SOUL's source, not the SOUL: the role
    page (or its working file) when there is one; the Manager's SOUL is its own source."""
    out = {"team-rules": ["workspace/AGENTS.md", "vault/system/team-habits.md", "vault/system/lessons.md"]}
    for prof in sorted((H / "profiles").glob("*")):
        if not (prof / "SOUL.md").exists():
            continue
        name, files = prof.name, []
        role = HOME / "vault" / "system" / "roles"
        if (role / f"{name}.working.md").exists():
            files += [f"vault/system/roles/{name}.working.md", f"vault/system/roles/{name}.md"]
        elif (role / f"{name}.md").exists():
            files += [f"vault/system/roles/{name}.md"]
        else:
            files += [f".hermes/profiles/{name}/SOUL.md"]
        files += [f"vault/team/{name}.md", f".hermes/profiles/{name}/memories/MEMORY.md",
                  f".hermes/profiles/{name}/memories/USER.md"]
        skills = prof / "skills"
        for sk in sorted(skills.rglob("SKILL.md")) if skills.is_dir() else []:
            r = sk.relative_to(skills)
            if r.parts[0] == "project" or any(x.startswith(".") for x in r.parts):
                continue                                 # template skills change by proposal with promote: template
            manifest = skills / ".bundled_manifest"
            if manifest.exists() and sk.parent.name in manifest.read_text():
                continue
            files.append(f".hermes/profiles/{name}/skills/{r.as_posix()}")
        out[f"bot:{name}"] = files
    out["vault-system"] = ["vault/system/overview.md", "vault/SCHEMA.md", "vault/design/brief.md", "vault/design/playbook.md"]
    return {k: [f for f in v if (HOME / f).exists()] for k, v in out.items()}


def units(text):
    """The lines that carry meaning: not blank, not frontmatter, not a heading, fence or table rule."""
    out, fm = [], text.startswith("---\n")
    for i, line in enumerate(text.splitlines()):
        if fm:
            if i > 0 and line.strip() == "---":
                fm = False
            continue
        s = line.strip()
        if not s or s.startswith(("#", "```")) or re.fullmatch(r"\|?[\s:|-]+\|?", s) or s.startswith("<!--"):
            continue
        out.append(s)
    return out


def soul_source(f):
    """The role page whose body becomes this SOUL, or None when the SOUL is its own source."""
    m = re.match(r"\.hermes/profiles/([^/]+)/SOUL\.md$", f)
    if not m:
        return None
    role = HOME / "vault" / "system" / "roles"
    for cand in (f"{m.group(1)}.working.md", f"{m.group(1)}.md"):
        if (role / cand).exists():
            return f"vault/system/roles/{cand}"
    return None


def body(text):
    return re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S).lstrip("\n")


def read_proposal(path):
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = HOME / "vault" / "system" / "changes" / p.name if not (HOME / p).exists() else HOME / p
    text = p.read_text(encoding="utf-8")
    m = re.search(r"^staged:\s*(\S+)", text, re.M)
    if not m:
        sys.exit(f"tidy: {p.name} has no staged: line")
    stage = HOME / m.group(1)
    return p, text, stage, json.loads((stage / "manifest.json").read_text())


def changed(stage, man):
    return [f for f in man["files"] if (stage / "new" / st(f)).exists() and
            (stage / "new" / st(f)).read_bytes() != ((stage / "old" / st(f)).read_bytes() if (stage / "old" / st(f)).exists() else b"")]


def do_check(path, quiet=False):
    p, text, stage, man = read_proposal(path)
    problems, ch = [], changed(stage, man)
    if not ch:
        problems.append("nothing changed in new/")
    for f in man["files"]:
        if sha(f) != man["files"][f]:
            problems.append(f"{f} changed since it was staged (stale: stage it again)")
    mp = (stage / "meaning-map.md").read_text(encoding="utf-8") if (stage / "meaning-map.md").exists() else ""
    sections = {m.group(1).strip("` "): m.group(2) for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", mp, re.M | re.S)}
    for f in ch:
        if re.match(r"\.hermes/profiles/[^/]+/SOUL\.md$", f) and soul_source(f):
            problems.append(f"{f}: change its source {soul_source(f)} instead (the SOUL is generated from it)")
        n = len(units((stage / "old" / st(f)).read_text(encoding="utf-8"))) if (stage / "old" / st(f)).exists() else 0
        sec = sections.get(f)
        if n and sec is None:
            problems.append(f"{f}: no section in the meaning map")
            continue
        seen = {}
        for m in re.finditer(r"^\s*-\s*U(\d+)\s+(\w+)\s*:?\s*(.*)$", sec or "", re.M):
            rest = m.group(3).split(" :: ")[0].strip()           # after " :: " is the unit's own text, for reference
            seen.setdefault(int(m.group(1)), []).append((m.group(2).lower(), rest))
        missing = [i for i in range(1, n + 1) if i not in seen]
        if missing:
            problems.append(f"{f}: units not accounted for: {', '.join('U%d' % i for i in missing[:20])}"
                            + (" …" if len(missing) > 20 else ""))
        for i, entries in seen.items():
            for kind, rest in entries:
                if kind not in KINDS:
                    problems.append(f"{f} U{i}: '{kind}' isn't one of {', '.join(KINDS)}")
                elif kind == "removed" and len(rest) < 12:
                    problems.append(f"{f} U{i}: removed needs its reason")
                elif kind == "moved":
                    dest = re.search(r"`([^`]+)`", rest)
                    d = dest.group(1).split("#")[0] if dest else ""
                    if not d or not ((stage / "new" / st(d)).exists() or (HOME / d).exists()):
                        problems.append(f"{f} U{i}: moved to `{d or '?'}`, which doesn't exist")
                elif kind == "merged" and not re.search(r"U\d+|`[^`]+`", rest):
                    problems.append(f"{f} U{i}: merged needs the unit (U<n>) or file it merged into")
    if any(LOADED.match(f) for f in ch):
        v = re.search(r"^Eval verdict:\s*(.+)$", text, re.M)
        if not v or not re.match(r"no worse|better", v.group(1).strip(), re.I):
            problems.append("a file the bots load changed: the proposal needs 'Eval verdict: no worse' (or better), "
                            "from run-eval.sh before and with --trial")
    if not quiet:
        print(f"{p.name}: " + ("PASS" if not problems else "FAIL") + f" ({len(ch)} file(s) changed)")
        for x in problems:
            print("  - " + x)
    return p, text, stage, man, ch, problems


def regenerate_souls(files):
    """Each SOUL whose source changed is written again from that source's body."""
    done = []
    for prof in sorted((H / "profiles").glob("*")):
        src = soul_source(f".hermes/profiles/{prof.name}/SOUL.md")
        if src and src in files:
            (prof / "SOUL.md").write_text(body((HOME / src).read_text(encoding="utf-8")), encoding="utf-8")
            done.append(f".hermes/profiles/{prof.name}/SOUL.md")
    return done


def sync_team_rules():
    """The team rules' template copy (import-project.sh renders new imports from it) follows AGENTS.md, keeping its
    own team table."""
    tr = H / "scripts" / "templates" / "team-rules.md"
    ag = (HOME / "workspace" / "AGENTS.md").read_text(encoding="utf-8")
    if not tr.exists():
        return
    old = tr.read_text(encoding="utf-8")
    m = re.search(r"<!-- team:start -->.*?<!-- team:end -->", old, re.S)
    new = re.sub(r"<!-- team:start -->.*?<!-- team:end -->", lambda _: m.group(0), ag, flags=re.S) if m else ag
    tr.write_text(new, encoding="utf-8")


def commit(files, msg):
    if "workspace/AGENTS.md" in files:
        subprocess.run(["git", "-C", str(HOME / "workspace"), "commit", "-q", "-m", msg, "--", "AGENTS.md"], capture_output=True)
    vault = [f for f in files if not f.startswith("workspace/")]
    if vault:
        subprocess.run(["bash", str(H / "scripts" / "vault-commit.sh"), "manager", msg, *vault], capture_output=True)


def set_status(p, text, status):
    text = re.sub(r"^status:.*$", f"status: {status}", text, count=1, flags=re.M)
    p.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")


def cmd_new(slice_):
    sl = slices()
    if slice_ not in sl:
        sys.exit(f"tidy: no slice {slice_} ({', '.join(sl)})")
    day = datetime.date.today().isoformat()
    name = f"{day}-{slice_.replace(':', '-')}"
    stage = STAGE / name
    if stage.exists():
        shutil.rmtree(stage)
    man = {"slice": slice_, "files": {}}
    lines = ["# Meaning map", "Every unit of every file you changed: replace `?` with kept | rewritten | moved: `<path>` | "
             "merged: U<n> | removed: <why>. After ` :: ` is the unit's own text (left as it is). Files you didn't change "
             "need no section.", ""]
    for f in sl[slice_]:
        for d in ("old", "new"):
            (stage / d / st(f)).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(HOME / f, stage / d / st(f))
        man["files"][f] = sha(f)
        lines += [f"## {f}"] + [f"- U{i} ? :: {u[:110]}" for i, u in enumerate(units((HOME / f).read_text(encoding='utf-8')), 1)] + [""]
    (stage / "manifest.json").write_text(json.dumps(man, indent=1))
    (stage / "meaning-map.md").write_text("\n".join(lines), encoding="utf-8")
    prop = HOME / "vault" / "system" / "changes" / f"{day}-tidy-{slice_.replace(':', '-')}.md"
    prop.parent.mkdir(parents=True, exist_ok=True)
    prop.write_text(f"""---
title: "Tidy: {slice_} ({day})"
type: system
status: draft
kind: tidy
slice: {slice_}
staged: {rel(stage)}
author: optimiser
owner: manager
updated: {day}
summary: "Tonight's tidy of {slice_}: the same rules, said once, in the right place."
tags: [system, tidy]
---
# Tidy: {slice_}

## What changed and why
<one line per change: what moved where, what merged, what was rewritten, and the gain (bytes loaded per session)>

## Files
{chr(10).join(f"- `{f}`" for f in sl[slice_])}

## Meaning map
`{rel(stage)}/meaning-map.md`; `tidy.py check` passes.

## Eval
Before: <vault/system/evals/results/...>; with the change: <... --trial ...>.
Eval verdict: <no worse | better | worse: then don't propose it>
""", encoding="utf-8")
    print(json.dumps({"stage": rel(stage), "edit": f"{rel(stage)}/new/ (instruction files as <name>.staged)",
                      "map": f"{rel(stage)}/meaning-map.md",
                      "proposal": rel(prop), "files": sl[slice_]}))


def cmd_add(stage_arg, f):
    """Stage one more file (a destination something moves to): copied to old/ and new/, added to the manifest and the map."""
    stage = HOME / stage_arg if not pathlib.Path(stage_arg).is_absolute() else pathlib.Path(stage_arg)
    man = json.loads((stage / "manifest.json").read_text())
    f = rel(HOME / f) if (HOME / f).exists() else f
    for d in ("old", "new"):
        (stage / d / st(f)).parent.mkdir(parents=True, exist_ok=True)
        if (HOME / f).exists():
            shutil.copy(HOME / f, stage / d / st(f))
    man["files"][f] = sha(f)
    (stage / "manifest.json").write_text(json.dumps(man, indent=1))
    us = units((HOME / f).read_text(encoding="utf-8")) if (HOME / f).exists() else []
    with (stage / "meaning-map.md").open("a", encoding="utf-8") as fh:
        fh.write("\n".join([f"## {f}"] + [f"- U{i} ? :: {u[:110]}" for i, u in enumerate(us, 1)]) + "\n\n")
    print(f"staged {f} ({len(us)} units)")


def cmd_apply(path, owner_present=False):
    p, text, stage, man, ch, problems = do_check(path)
    if problems:
        sys.exit("tidy: not applied (see above); the proposal goes back to the Optimiser")
    if touches_instructions(ch) and not owner_present:
        print("tidy: this one changes an instruction file (" + ", ".join(f for f in ch if touches_instructions([f]))
              + "): Hermes lets those change only with a person there. Put it to the owner (one Owner: card, blocked "
              "needs_input), and after their yes run, in that chat: tidy.py apply " + p.name + " --owner-present")
        sys.exit(3)
    for f in ch:
        (stage / "backup" / f).parent.mkdir(parents=True, exist_ok=True)
        if (HOME / f).exists():
            shutil.copy(HOME / f, stage / "backup" / f)
    souls_before = {}
    for prof in sorted((H / "profiles").glob("*")):
        s = f".hermes/profiles/{prof.name}/SOUL.md"
        if soul_source(s) in ch:
            (stage / "backup" / s).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(HOME / s, stage / "backup" / s)
            souls_before[s] = True
    for f in ch:
        (HOME / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(stage / "new" / st(f), HOME / f)
    souls = regenerate_souls(ch)
    if "workspace/AGENTS.md" in ch:
        sync_team_rules()
    msg = f"Tidy {man['slice']} ({p.name})"
    commit(ch + souls, msg)
    subprocess.run(["bash", str(H / "scripts" / "vault-log.sh"), "manager", "decision",
                    f"Applied the Optimiser's tidy of {man['slice']}: {len(ch)} file(s), meaning map checked "
                    f"(rollback: tidy.py rollback {p.name})", f"system/changes/{p.stem}"], capture_output=True)
    applied = HOME / "vault" / "system" / "optimiser" / "applied.md"
    applied.parent.mkdir(parents=True, exist_ok=True)
    if not applied.exists() or not applied.read_text(encoding="utf-8").startswith("---\n"):
        old = applied.read_text(encoding="utf-8") if applied.exists() else ""
        applied.write_text(APPLIED_HEAD.format(day=datetime.date.today()) + old.lstrip("\n"), encoding="utf-8")
    first = re.search(r"^## What changed and why\n+(.+)$", text, re.M)
    with applied.open("a", encoding="utf-8") as fh:
        fh.write(f"- {datetime.datetime.now():%Y-%m-%d %H:%M} tidy {man['slice']}: {(first.group(1) if first else '')[:160]} "
                 f"([[system/changes/{p.stem}]]; rollback: `tidy.py rollback {p.name}`)\n")
    set_status(p, re.sub(r"^updated:.*$", f"updated: {datetime.date.today()}", text, count=1, flags=re.M), "applied")
    print(f"applied {len(ch)} file(s)" + (f"; regenerated {', '.join(souls)}" if souls else ""))


def cmd_rollback(path):
    p, text, stage, man = read_proposal(path)
    back = stage / "backup"
    if not back.is_dir():
        sys.exit("tidy: no backup (never applied?)")
    files = [x.relative_to(back).as_posix() for x in back.rglob("*") if x.is_file()]
    for f in files:
        shutil.copy(back / f, HOME / f)
    if "workspace/AGENTS.md" in files:
        sync_team_rules()
    commit(files, f"Roll back tidy {man['slice']} ({p.name})")
    subprocess.run(["bash", str(H / "scripts" / "vault-log.sh"), "manager", "decision",
                    f"Rolled back the tidy of {man['slice']} ({p.name})", f"system/changes/{p.stem}"], capture_output=True)
    set_status(p, text, "rolled-back")
    print(f"rolled back {len(files)} file(s)")


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = a[0], a[1:]
    if cmd == "slices":
        sl = slices()
        print(json.dumps(sl) if "--json" in rest else "\n".join(f"{k}: {', '.join(v)}" for k, v in sl.items()))
    elif cmd == "units" and rest:
        for i, u in enumerate(units(pathlib.Path(rest[0]).read_text(encoding="utf-8")), 1):
            print(f"U{i}: {u[:150]}")
    elif cmd == "new" and rest:
        cmd_new(rest[0])
    elif cmd == "add" and len(rest) == 2:
        cmd_add(rest[0], rest[1])
    elif cmd == "check" and rest:
        return 1 if do_check(rest[0])[5] else 0
    elif cmd == "apply" and rest:
        cmd_apply(rest[0], owner_present="--owner-present" in rest)
    elif cmd == "rollback" and rest:
        cmd_rollback(rest[0])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
