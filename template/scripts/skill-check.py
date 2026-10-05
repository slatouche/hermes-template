#!/usr/bin/python3
"""Check a skill folder before a bot gets it, with no model. Run by hire.sh for every --skill, and by the
Manager on any skill kept from an imported project.

  skill-check.py <skill folder>      exit 0 = clean, 1 = needs a person to look (findings printed)

A skill is instructions a bot will follow, so one copied from elsewhere can carry planted instructions.
This looks for the common signs: text addressed to the model ("ignore previous instructions"), hidden text
(HTML comments, zero-width or tag characters, long encoded blobs), commands that fetch and run code or send
data out, reads of secrets, and files that aren't text. It can't prove a skill is safe; it catches the
obvious, and anything it flags is rewritten or removed before use.
"""
import pathlib
import re
import sys

TEXT_EXT = {".md", ".txt", ".py", ".sh", ".bash", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".csv", ".html"}
RULES = [
    ("instruction aimed at the model", re.compile(
        r"ignore (all |any )?(previous|prior|above|earlier) (instructions|rules)|disregard (the|your|all) (instructions|rules|system)"
        r"|you are now (a|an|in) |new system prompt|reveal (your|the) system prompt|do not (tell|inform|show) (the )?(user|owner)"
        r"|without (telling|asking) the (user|owner)|bypass (the )?(approval|guard|safety)", re.I)),
    ("downloads and runs code", re.compile(
        r"(curl|wget)[^\n|;]*\|\s*(sudo\s+)?(ba|z)?sh\b|bash\s+<\(\s*(curl|wget)|base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh"
        r"|python3?\s+-c\s+[\"'].*(urllib|requests|socket)", re.I)),
    ("sends data out", re.compile(
        r"(curl|wget)[^\n]*(--data|-d\s|-F\s|--upload-file|-T\s)[^\n]*(https?://)|nc\s+-\w*\s+\S+\s+\d+|/dev/tcp/", re.I)),
    ("touches secrets", re.compile(
        r"\.env\b(?!\.example)|\.ssh/|id_(rsa|ed25519)|API_SERVER_KEY|_API_KEY|\bTOKEN\b|\.git-credentials|/etc/(shadow|sudoers)", re.I)),
    ("destructive or privileged", re.compile(r"rm\s+-rf\s+(/|~|\$HOME)(\s|$)|\bsudo\b|chmod\s+777|mkfs|dd\s+if=", re.I)),
    ("changes Hermes itself", re.compile(r"\.hermes/(config\.yaml|\.env|profiles/[^/\s]+/(SOUL|config))|hermes\s+(config\s+set|skills\s+trust)", re.I)),
]
HIDDEN = [
    ("zero-width or invisible characters", re.compile("[​-‏⁠-⁤﻿]")),
    ("Unicode tag characters (invisible text)", re.compile("[\U000e0000-\U000e007f]")),
    ("long encoded blob", re.compile(r"[A-Za-z0-9+/=]{300,}")),
]
COMMENT = re.compile(r"<!--(.*?)-->", re.S)


def main() -> int:
    if len(sys.argv) != 2 or not pathlib.Path(sys.argv[1]).is_dir():
        print("usage: skill-check.py <skill folder>", file=sys.stderr)
        return 2
    root = pathlib.Path(sys.argv[1])
    found = []
    if not (root / "SKILL.md").is_file():
        found.append("no SKILL.md")
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = f.relative_to(root).as_posix()
        if f.suffix.lower() not in TEXT_EXT:
            found.append(f"{rel}: not a text file ({f.suffix or 'no extension'}); a skill should be readable text")
            continue
        text = f.read_text(errors="replace")
        for name, rx in HIDDEN:
            if rx.search(text):
                found.append(f"{rel}: {name}")
        for m in COMMENT.finditer(text):
            if len(m.group(1).strip()) > 40:
                found.append(f"{rel}: HTML comment with text in it (hidden from a reader, not from a bot): {m.group(1).strip()[:80]!r}")
        for n, line in enumerate(text.splitlines(), 1):
            for name, rx in RULES:
                if rx.search(line):
                    found.append(f"{rel}:{n}: {name}: {line.strip()[:120]}")
    urls = sorted({u for f in root.rglob("*") if f.is_file() and f.suffix.lower() in TEXT_EXT
                   for u in re.findall(r"https?://[^\s)\"'>]+", f.read_text(errors="replace"))})
    print(f"skill-check {root}: {len(found)} finding(s)")
    for x in found:
        print(f"- {x}")
    if urls:
        print("links in it (check they're expected): " + ", ".join(urls[:15]))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
