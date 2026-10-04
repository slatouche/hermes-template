#!/usr/bin/python3
"""Regenerate vault/index.md from each page's frontmatter. Bots never edit index.md.

Each entry: - [[path]]: <summary>   (falls back to <title> when a page has no `summary`).
Pages are grouped by top-level folder in the order SCHEMA.md lists them; unknown folders go last.
Writes atomically (temp file + rename) and only when the content actually changed.
Usage: vault-index.py [vault_dir]
"""
import os
import pathlib
import sys
import tempfile
import datetime
import yaml

FOLDER_ORDER = ["product", "architecture", "design", "plans", "qa", "team", "research", "raw"]
ROOT_PAGES = ["SCHEMA", "00-status", "log"]
NOT_PAGES = ("raw/predecessor/snapshot/", "raw/predecessor/notes/", "system/skills/")   # copied evidence and skill folders: not vault pages


def frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(errors="replace")
    if not text.startswith("---\n"):
        return {}
    block = text.split("---", 2)[1]
    try:
        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass
    # Broken YAML (lint will flag it): fall back to simple "key: value" lines so the index still works.
    data = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip().strip("\"'")
    return data


def main() -> int:
    vault = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/vault"))
    pages = {}
    for p in sorted(vault.rglob("*.md")):
        if ".git" in p.parts:
            continue
        name = p.relative_to(vault).with_suffix("").as_posix()
        if name == "index" or name.startswith(NOT_PAGES):
            continue
        fm = frontmatter(p)
        summary = str(fm.get("summary") or fm.get("title") or name).strip().replace("\n", " ")
        status = fm.get("status")
        if status in ("superseded", "archived"):
            summary += f" _({status})_"
        pages[name] = summary

    groups = {}
    for name, summary in pages.items():
        folder = name.split("/")[0] if "/" in name else ""
        groups.setdefault(folder, []).append(f"- [[{name}]]: {summary}")

    lines = [
        "---", "title: Index", "type: note", "status: active", "owner: all",
        f"updated: {datetime.date.today().isoformat()}", "summary: Generated catalogue of every page. Do not edit.",
        "tags: [index]", "---", "# Index", "",
        "_Generated from each page's frontmatter every few minutes. Do not edit; give your page a good `summary:` instead._", "",
        "## Root",
    ]
    lines += [f"- [[{n}]]: {pages[n]}" for n in ROOT_PAGES if n in pages]
    lines += [e for e in groups.get("", []) if not any(e.startswith(f"- [[{n}]]") for n in ROOT_PAGES)]
    for folder in FOLDER_ORDER + sorted(set(groups) - set(FOLDER_ORDER) - {""}):
        lines += ["", f"## {folder}/"] + groups.get(folder, [])
    new = "\n".join(lines) + "\n"

    target = vault / "index.md"
    old = target.read_text() if target.exists() else ""
    # ignore the 'updated:' line when deciding whether anything changed
    strip = lambda s: "\n".join(l for l in s.splitlines() if not l.startswith("updated:"))
    if strip(old) == strip(new):
        return 0
    fd, tmp = tempfile.mkstemp(dir=vault, prefix=".index.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(new)
    os.replace(tmp, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
