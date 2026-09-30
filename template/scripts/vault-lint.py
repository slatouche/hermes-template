#!/usr/bin/env python3
"""Vault lint. Installed at ~/.hermes/scripts/vault-lint.py and run nightly by the `vault-lint`
Hermes job (no-agent). The Architect owns the lint RULES and changes this file only with the
owner's approval; improvements are flagged "promote to template" like core SCHEMA changes.
Originally written by the Architect in scratch/ (hermes-test pilot, 2026-09-30).

Checks, per SCHEMA.md:
- frontmatter must be present and must **parse as YAML**
- required frontmatter fields are present, including ``summary:`` (it is the index entry)
- broken wikilinks, and orphan pages (no inbound links)
- the 00-status.md contract (required fields, enum values, list types, frontmatter-vs-prose drift)
- stale ``updated`` dates on active pages

``index.md`` is generated, so index drift is no longer checked — a page **missing ``summary:``** is.

Wikilinks inside inline code spans or fenced blocks are illustrative, not links, and are stripped
before checking — otherwise SCHEMA.md and log.md produce false positives.

Known exemptions (see the constants below):
- ``log.md`` is **append-only**, so an example link in an old line can never be corrected and
  flagging it would be permanent noise. Its link targets are not checked. ``vault-log.sh`` now
  prevents the two historical shapes: it neutralises ``[[..]]`` inside the text and strips
  brackets from the link argument, so only its own single trailing link is ever a link.
- ``log.md`` also has no ``summary:`` check: nobody may edit its frontmatter.

Run me with **/usr/bin/python3** (it has PyYAML; the Hermes-toolchain python3 does not).

Usage:  /usr/bin/python3 vault-lint.py [vault_dir] [--stale-days=N]
"""
import re
import sys
import pathlib
import datetime

try:                                     # PyYAML is the one non-stdlib need; degrade loudly if absent
    import yaml
except ImportError:                      # pragma: no cover
    yaml = None

EXEMPT_FRONTMATTER = {"SCHEMA"}          # the rules file itself, deliberately bare
EXEMPT_ORPHAN = {"index", "log", "SCHEMA", "00-status"}
EXEMPT_SUMMARY = {"log"}                 # append-only via vault-log.sh: nobody may edit its frontmatter
EXEMPT_LINKS = {"log"}                   # append-only: example links in old lines cannot be corrected
REQUIRED_FIELDS = ("title", "type", "status", "owner", "updated", "summary")

# Contract defined in SCHEMA.md — the fields tools read from 00-status.md.
STATUS_PHASES = {"setup", "gate-1", "gate-2", "gate-3", "gate-4", "build", "done"}
STATUS_ACTIVE_GATES = {"none", "1", "2", "3", "4"}
STATUS_REQUIRED = ("phase", "active_gate")
STATUS_LIST_FIELDS = ("gates_approved", "waiting_on_owner", "blockers")


def strip_code(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    return text


def read_frontmatter(path: pathlib.Path):
    """Return (block_text, parsed_dict_or_None, parse_error_or_None)."""
    raw = path.read_text()
    if not raw.startswith("---\n"):
        return None, None, None
    block = raw.split("---", 2)[1]
    if yaml is None:
        return block, None, None
    try:
        parsed = yaml.safe_load(block)
    except Exception as exc:                                   # noqa: BLE001 - report, never crash
        return block, None, str(exc).replace("\n", " ")
    if not isinstance(parsed, dict):
        return block, None, "frontmatter does not parse to a mapping"
    return block, parsed, None


def check_status_contract(root: pathlib.Path, problems: list, advisories: list) -> None:
    """SCHEMA.md gives 00-status.md structured frontmatter that must match the prose."""
    path = root / "00-status.md"
    if not path.exists():
        return
    if yaml is None:
        advisories.append("00-status: skipped contract check (PyYAML absent — run me with /usr/bin/python3)")
        return
    _block, fm, err = read_frontmatter(path)
    if err:
        problems.append(f"00-status: frontmatter is not valid YAML ({err})")
        return
    if fm is None:
        return

    for key in STATUS_REQUIRED:
        if fm.get(key) is None:
            problems.append(f"00-status: missing required SCHEMA field '{key}'")
    if fm.get("phase") is not None and str(fm["phase"]) not in STATUS_PHASES:
        advisories.append(f"00-status: 'phase' value {fm['phase']!r} is not one of {sorted(STATUS_PHASES)}")
    if fm.get("active_gate") is not None and str(fm["active_gate"]) not in STATUS_ACTIVE_GATES:
        advisories.append(f"00-status: 'active_gate' value {fm['active_gate']!r} is not one of {sorted(STATUS_ACTIVE_GATES)}")
    for key in STATUS_LIST_FIELDS:
        if key in fm and not isinstance(fm[key], list):
            problems.append(f"00-status: '{key}' must be a list, found {type(fm[key]).__name__}")

    # Heuristic drift check: SCHEMA says frontmatter and prose must agree.
    prose = path.read_text().split("---", 2)[2]
    gate_line = re.search(r"\*\*Active gate:\*\*\s*(.+)", prose)
    if fm.get("active_gate") == "none" and gate_line and "none" not in gate_line.group(1).lower():
        advisories.append("00-status: prose 'Active gate' disagrees with frontmatter active_gate=none")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = pathlib.Path(args[0] if args else ".")
    stale_days = 30
    for a in sys.argv[1:]:
        if a.startswith("--stale-days"):
            stale_days = int(a.split("=", 1)[1])

    pages = {p.relative_to(root).with_suffix("").as_posix(): p
             for p in root.rglob("*.md") if ".git" not in p.parts}
    today = datetime.date.today()
    problems, advisories = [], []
    check_status_contract(root, problems, advisories)

    for name, path in sorted(pages.items()):
        raw = path.read_text()
        body = strip_code(raw)

        if name not in EXEMPT_FRONTMATTER:
            block, parsed, err = read_frontmatter(path)
            if block is None:
                problems.append(f"{name}: no frontmatter")
            elif err:
                problems.append(f"{name}: frontmatter does not parse as YAML ({err})")
            for key in REQUIRED_FIELDS:
                if key == "summary" and name in EXEMPT_SUMMARY:
                    continue
                present = (key in parsed) if parsed is not None else bool(re.search(rf"^{key}:", block or "", re.M))
                if not present:
                    problems.append(f"{name}: frontmatter missing '{key}'")
            if parsed is not None:
                status = parsed.get("status")
                updated = parsed.get("updated")
                if status == "active" and isinstance(updated, datetime.date):
                    age = (today - updated).days
                    if age > stale_days:
                        advisories.append(f"{name}: active but updated {age}d ago")

        if name not in EXEMPT_LINKS:          # append-only pages: their old example links are frozen
            for link in re.findall(r"\[\[([^\]]+?)\]\]", body):
                target = link.split("|")[0].split("#")[0].strip()
                if target and target not in pages:
                    problems.append(f"{name}: broken link [[{link}]]")

    for name in sorted(pages):
        if name in EXEMPT_ORPHAN:
            continue
        inbound = [o for o, p in pages.items() if o != name and name in re.findall(r"\[\[([^\]]+?)\]\]", strip_code(p.read_text()))]
        if not inbound:
            problems.append(f"{name}: orphan (no inbound links)")

    print(f"pages: {len(pages)}")
    print("--- problems ---")
    print("\n".join(problems) if problems else "none")
    print("--- advisories ---")
    print("\n".join(advisories) if advisories else "none")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
