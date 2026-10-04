#!/usr/bin/python3
"""Survey an imported project, with no model tokens. Run once by setup-agent.sh after an import, and by the
Manager whenever it wants a fresh picture (it's read-only on the workspace).

  import-survey.py [--snapshot]
  import-survey.py --notes <folder>     copy an old bot's notes into vault/raw/predecessor/notes/

Writes vault/raw/predecessor/inventory.md: the repo's shape (history, size, languages, docs, how it seems to
run and test, CI), every file left by another AI tool (Claude Code, Codex, Cursor, Copilot, Gemini, Aider,
another Hermes...), and anything tracked that looks like a secret.
With --snapshot it also copies those AI-tool files into vault/raw/predecessor/snapshot/, so the know-how
survives the cleanup as evidence. Files that look like they hold a secret are never copied, only listed.
The snapshot is evidence, not instructions: lint and the index skip it.
"""
import collections
import datetime
import pathlib
import re
import shutil
import subprocess
import sys

HOME = pathlib.Path.home()
WS = HOME / "workspace"
OUT = HOME / "vault" / "raw" / "predecessor"
SNAP = OUT / "snapshot"
MAX_COPY = 200_000                       # bytes; bigger AI-tool files are listed, not copied

# Files and folders other AI tools leave in a repo. Folder entries end with "/".
AI_TOOL_PATTERNS = {
    "Hermes": [".hermes.md", "HERMES.md", ".hermes/"],
    "Codex / agents.md": ["AGENTS.md", "AGENTS.override.md", "agents.md", ".codex/", ".agents/"],
    "Claude Code": ["CLAUDE.md", "CLAUDE.local.md", "claude.md", ".claude/", ".mcp.json"],
    "Cursor": [".cursorrules", ".cursor/", ".cursorignore"],
    "GitHub Copilot": [".github/copilot-instructions.md", ".github/instructions/", ".github/prompts/", ".github/chatmodes/"],
    "Gemini": ["GEMINI.md", ".gemini/"],
    "Windsurf": [".windsurfrules", ".windsurf/"],
    "Cline / Roo": [".clinerules", ".clinerules/", ".roo/", ".roomodes"],
    "Aider": [".aider.conf.yml", ".aider.chat.history.md", ".aider.input.history", ".aider.tags.cache.v3/"],
    "Continue": [".continue/", ".continuerules"],
    "Kiro": [".kiro/"],
    "Junie": [".junie/"],
    "Zed": [".rules"],
    "Amazon Q": [".amazonq/"],
    # Often real project docs, not tool leftovers: listed so the takeover decides, never removed by default.
    "Agent working notes (may be real docs)": ["TASKS.md", "TODO.md", "HANDOFF.md", "PROGRESS.md", "NOTES.md",
                                               "CONVENTIONS.md", "memory-bank/", ".specstory/"],
}
SECRET_NAME = re.compile(r"(^|/)(\.env(\.[^/]*)?|[^/]*\.pem|[^/]*\.key|id_(rsa|ed25519|ecdsa)[^/]*"
                         r"|[^/]*credentials[^/]*\.(json|ya?ml|txt)|[^/]*secrets?\.(json|ya?ml|txt|toml))$", re.I)
SECRET_TEXT = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|xox[abpr]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-/+=]{16,})", re.I)
EXT_LANG = {".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript",
            ".mjs": "JavaScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".cs": "C#",
            ".cpp": "C++", ".c": "C", ".h": "C/C++", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
            ".sh": "Shell", ".ps1": "PowerShell", ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".vue": "Vue",
            ".svelte": "Svelte", ".sql": "SQL", ".md": "Markdown", ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
            ".toml": "TOML", ".ipynb": "Notebook", ".lua": "Lua", ".dart": "Dart"}


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(WS), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def tracked() -> list[str]:
    out = git("ls-files", "-z")
    return [f for f in out.split("\0") if f] if out else []


def looks_secret(path: pathlib.Path) -> bool:
    try:
        if path.stat().st_size > 2_000_000:
            return False
        return bool(SECRET_TEXT.search(path.read_text(errors="ignore")))
    except OSError:
        return False


def ai_tool_files(files: list[str]) -> dict[str, list[str]]:
    """Tracked AI-tool files plus untracked ones on disk, grouped by tool. Paths are relative to the workspace."""
    on_disk = set(files)
    for p in WS.rglob("*"):
        if ".git" in p.parts or not p.is_file():
            continue
        rel = p.relative_to(WS).as_posix()
        if any(part in ("node_modules", ".venv", "venv", "__pycache__") for part in p.parts):
            continue
        on_disk.add(rel)
    found = collections.defaultdict(list)
    for tool, pats in AI_TOOL_PATTERNS.items():
        for pat in pats:
            for rel in sorted(on_disk):
                name_match = (rel == pat or rel.endswith("/" + pat)) if not pat.endswith("/") else \
                             (rel.startswith(pat) or ("/" + pat) in "/" + rel)
                if name_match and rel not in found[tool]:
                    found[tool].append(rel)
    return {t: v for t, v in found.items() if v}


def run_hints(files: list[str]) -> list[str]:
    hints = []
    names = set(files)
    if "package.json" in names:
        try:
            import json
            scripts = json.loads((WS / "package.json").read_text()).get("scripts", {})
            hints += [f"npm script `{k}`: `{v}`" for k, v in list(scripts.items())[:12]]
        except (ValueError, OSError):
            hints.append("package.json (could not read scripts)")
    for f in ("pyproject.toml", "setup.py", "requirements.txt", "uv.lock", "poetry.lock", "Pipfile", "Cargo.toml",
              "go.mod", "pom.xml", "build.gradle", "Gemfile", "composer.json", "Makefile", "justfile", "Taskfile.yml",
              "Dockerfile", "docker-compose.yml", "compose.yaml", "pytest.ini", "tox.ini", "noxfile.py",
              "vitest.config.ts", "jest.config.js", "playwright.config.ts"):
        if f in names:
            hints.append(f"`{f}`")
    if "Makefile" in names:
        targets = re.findall(r"^([A-Za-z0-9_.-]+):", (WS / "Makefile").read_text(errors="ignore"), re.M)
        if targets:
            hints.append("make targets: " + ", ".join(sorted(set(targets))[:15]))
    ci = [f for f in files if f.startswith(".github/workflows/") or f in (".gitlab-ci.yml", "azure-pipelines.yml")]
    hints += [f"CI: `{f}`" for f in ci[:8]]
    test_dirs = sorted({f.split("/")[0] for f in files if re.match(r"(tests?|spec|__tests__)/", f)})
    test_files = [f for f in files if re.search(r"(^|/)(test_[^/]+\.py|[^/]+_test\.(py|go)|[^/]+\.(test|spec)\.[jt]sx?)$", f)]
    if test_dirs or test_files:
        hints.append(f"tests: {len(test_files)} test files" + (f", folders {', '.join(test_dirs)}" if test_dirs else ""))
    return hints


def import_notes(src: pathlib.Path) -> int:
    """Copy an old bot's notes (memory, owner notes, skills) as evidence; skip anything that looks secret."""
    dst = OUT / "notes"
    copied, skipped = 0, []
    for f in sorted(src.rglob("*")):
        if not f.is_file() or any(part.startswith(".git") for part in f.parts):
            continue
        rel = f.relative_to(src).as_posix()
        if SECRET_NAME.search(rel) or looks_secret(f) or f.suffix.lower() in (".db", ".sqlite", ".lock"):
            skipped.append(rel); continue
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst / rel)
        copied += 1
    print(f"import-survey: notes: {copied} file(s) copied to raw/predecessor/notes/"
          + (f"; skipped (secret-like or database): {', '.join(skipped)}" if skipped else ""))
    return 0


def main() -> int:
    if sys.argv[1:2] == ["--notes"]:
        if len(sys.argv) < 3 or not pathlib.Path(sys.argv[2]).is_dir():
            print("usage: import-survey.py --notes <folder>", file=sys.stderr)
            return 2
        return import_notes(pathlib.Path(sys.argv[2]))
    snapshot = "--snapshot" in sys.argv[1:]
    if not (WS / ".git").is_dir():
        print("import-survey: no git repo in ~/workspace", file=sys.stderr)
        return 1
    files = tracked()
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()

    commits = git("rev-list", "--count", "HEAD") or "0"
    first = git("log", "--reverse", "--format=%ad", "--date=short").split("\n")[0] if commits != "0" else "-"
    last = git("log", "-1", "--format=%ad %s", "--date=short") or "-"
    branches = git("branch", "-a", "--format=%(refname:short)").splitlines()
    remotes = git("remote", "-v").splitlines()
    remotes = sorted({re.sub(r"//[^@/]+@", "//", r.split()[1]) for r in remotes if len(r.split()) > 1})
    size_mb = sum((WS / f).stat().st_size for f in files if (WS / f).is_file()) / 1e6

    langs = collections.Counter(EXT_LANG.get(pathlib.Path(f).suffix.lower(), None) for f in files)
    langs.pop(None, None)
    top = collections.Counter(f.split("/")[0] + ("/" if "/" in f else "") for f in files)
    docs = [f for f in files if f.lower().endswith(".md")]
    readmes = [f for f in docs if pathlib.Path(f).name.lower().startswith("readme")]
    secret_like = [f for f in files if SECRET_NAME.search(f) and not f.endswith((".example", ".sample", ".template"))]
    # Content scan of tracked text files (capped, so a huge repo stays quick).
    secret_text = [f for f in files[:20000] if f not in secret_like and (WS / f).is_file()
                   and (WS / f).stat().st_size < MAX_COPY and looks_secret(WS / f)]
    ai = ai_tool_files(files)

    copied, withheld, too_big = [], [], []
    if snapshot:
        if SNAP.exists():
            shutil.rmtree(SNAP)
        for tool, rels in ai.items():
            for rel in rels:
                src = WS / rel
                if not src.is_file():
                    continue
                if SECRET_NAME.search(rel) or looks_secret(src):
                    withheld.append(rel); continue
                if src.stat().st_size > MAX_COPY:
                    too_big.append(rel); continue
                dst = SNAP / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append(rel)

    L = ["---", "title: Import inventory", "type: research", "status: active", "owner: manager",
         f"updated: {today}", "summary: \"Generated survey of the imported repo - shape, how it runs, other AI tools' files, secret risks.\"",
         "tags: [import, predecessor, generated]", "---",
         "# Import inventory",
         "",
         f"_Generated by `import-survey.py` on {today}. Re-run it for a fresh picture; don't edit this page._",
         "",
         "## The repo",
         f"- Commits: {commits} (first {first}; last {last})",
         f"- Branches: {', '.join(branches[:10]) or '-'}",
         f"- Remotes: {', '.join(remotes) or 'none'}",
         f"- Tracked files: {len(files)}, {size_mb:.1f} MB",
         f"- Languages (by file count): " + (", ".join(f"{k} {v}" for k, v in langs.most_common(8)) or "-"),
         f"- Top level: " + ", ".join(f"`{k}` ({v})" for k, v in sorted(top.items())[:40]),
         "",
         "## Start here (docs)",
         f"- READMEs: " + (", ".join(f"`{r}`" for r in readmes[:10]) or "none"),
         f"- Markdown files: {len(docs)}" + (" (first 30 below)" if docs else ""),
         ]
    L += [f"  - `{d}`" for d in docs[:30]]
    L += ["", "## How it seems to run and test"]
    L += [f"- {h}" for h in run_hints(files)] or ["- nothing obvious: ask or read the README"]
    L += ["", "## Files from other AI tools",
          "These are what the takeover reads, keeps the know-how from, then removes (with the owner's OK).",
          "Hermes loads only one instructions file: `.hermes.md` first, then `AGENTS.md`, then `CLAUDE.md`, then Cursor rules."]
    if ai:
        for tool, rels in ai.items():
            L.append(f"- **{tool}:** " + ", ".join(f"`{r}`" + ("" if r in files else " (untracked)") for r in rels[:25])
                     + (f" … and {len(rels) - 25} more" if len(rels) > 25 else ""))
    else:
        L.append("- none found")
    if snapshot:
        L += ["", "## Snapshot",
              f"Copied {len(copied)} file(s) to `raw/predecessor/snapshot/` (evidence, not instructions)."]
        if withheld:
            L.append("- **Not copied, may hold a secret** (read in place, never copy): " + ", ".join(f"`{w}`" for w in withheld))
        if too_big:
            L.append(f"- Not copied, over {MAX_COPY // 1000} KB (read in place): " + ", ".join(f"`{b}`" for b in too_big))
    L += ["", "## Secret risks in git"]
    L += [f"- `{s}` is tracked (name looks secret): check it; a real secret must be removed from git and rotated (owner)"
          for s in secret_like]
    L += [f"- `{s}` is tracked and contains something that looks like a key or password: check it; a real one must be removed from git and rotated (owner)"
          for s in secret_text]
    if not (secret_like or secret_text):
        L.append("- none found by file name or content")
    (OUT / "inventory.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"import-survey: {len(files)} files, {sum(len(v) for v in ai.values())} AI-tool file(s)"
          + (f", {len(copied)} copied, {len(withheld)} withheld" if snapshot else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
