#!/usr/bin/python3
"""Stamp a raw source in the vault with where it came from and a fingerprint of its content.

  raw-stamp.py <vault/raw/... file> [--source <url or path>]

Adds or updates `source:`, `ingested:` and `sha256:` in its frontmatter (creating frontmatter if it has none).
The nightly lint recomputes the fingerprint and says when a source has changed since it was ingested.
"""
import datetime, hashlib, pathlib, re, sys

args = sys.argv[1:]
if not args or not pathlib.Path(args[0]).is_file():
    sys.exit("usage: raw-stamp.py <file> [--source <url or path>]")
path = pathlib.Path(args[0])
source = args[args.index("--source") + 1] if "--source" in args else None
text = path.read_text(encoding="utf-8", errors="replace")
if text.startswith("---\n") and text.count("---") >= 2:
    _, head, body = text.split("---", 2)
    body = body.lstrip("\n")
else:
    head, body = f"\ntitle: {path.stem}\ntype: research\nstatus: active\nowner: manager\nupdated: {datetime.date.today()}\nsummary: \"Raw source: {path.stem}\"\n", text
digest = hashlib.sha256(body.encode()).hexdigest()
lines = [l for l in head.strip("\n").splitlines() if not re.match(r"^(sha256|ingested)\s*:", l)
         and not (source and re.match(r"^source\s*:", l))]
lines += ([f"source: \"{source}\""] if source else []) + [f"ingested: {datetime.date.today()}", f"sha256: {digest}"]
path.write_text("---\n" + "\n".join(lines) + "\n---\n" + body, encoding="utf-8")
print(f"raw-stamp: {path} sha256 {digest[:12]}")
