#!/bin/bash
# Bring an existing project into this install, as the project user (no sudo). Used by new-project.sh at
# creation, and by the Manager when the owner points it at a project later.
#
#   import-project.sh <source> [--notes <folder>] [--interactive]
#
# <source> is one of:
#   - a git URL (https://, ssh://, git@...). A private repo needs a token, which only a person in an SSH
#     terminal can type; from a chat, ask the owner to copy the repo folder or a bundle into ~/import/.
#   - a folder in ~/import/ (or anywhere this user can read) with a git repo: only committed files come in,
#     with full history. Untracked and ignored files stay where they are and are listed for the takeover.
#   - a folder without git: its files come in as one first commit (secrets, caches and venvs skipped).
#   - a .bundle file (git bundle create x.bundle --all).
# --notes <folder>: an old bot's notes (memory, owner notes, skills), copied as evidence.
# --interactive: a person is at the terminal (new-project.sh), so a private repo may ask for a token.
#
# Replaces workspace/ only while it still holds just the template's first commit; it never overwrites work.
# Afterwards: phase onboarding, the inventory in vault/raw/predecessor/, and the Manager's takeover starts.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
die() { echo "import-project: $*" >&2; exit 1; }
S="$HOME/.hermes/scripts"
W="$HOME/workspace"
V="$HOME/vault"
TODAY="$(date +%F)"

SRC="${1:-}"; [ -n "$SRC" ] || die "usage: import-project.sh <git url | folder | .bundle> [--notes <folder>]"
shift
NOTES=""; INTERACTIVE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --notes) NOTES="${2:-}"; shift 2 ;;
    --interactive) INTERACTIVE=1; shift ;;
    *) die "unknown option '$1'" ;;
  esac
done
[ -z "$NOTES" ] || [ -d "$NOTES" ] || die "--notes: '$NOTES' is not a folder"

# ---------- what kind of source ----------
if [[ "$SRC" =~ ^https://[^/]*@ ]]; then die "no credentials in the URL, please"
elif [[ "$SRC" =~ ^(https://|ssh://|git@) ]]; then KIND=url; LABEL="$(sed -E 's#\.git$##' <<<"$SRC")"
elif [ -f "$SRC" ]; then KIND=bundle; SRC="$(readlink -f "$SRC")"; LABEL="$(basename "$SRC")"
elif [ -d "$SRC" ] && [ -e "$SRC/.git" ]; then
  KIND=git; SRC="$(readlink -f "$SRC")"; LABEL="$(basename "$SRC")"
elif [ -d "$SRC" ]; then KIND=plain; SRC="$(readlink -f "$SRC")"; LABEL="$(basename "$SRC")"
else die "'$SRC' is not a git URL, a folder or a bundle file"; fi

# ---------- is workspace/ free? ----------
if [ -d "$W/.git" ]; then
  N="$(git -C "$W" rev-list --count HEAD 2>/dev/null || echo 0)"
  FIRST="$(git -C "$W" log --format=%s -1 2>/dev/null || true)"
  if [ "$N" -gt 1 ] || { [ "$N" = 1 ] && [ "$FIRST" != "Initialise workspace from the project template" ]; } \
     || [ -n "$(git -C "$W" status --porcelain 2>/dev/null)" ]; then
    die "workspace/ already has work in it ($N commits). Import only into a fresh project."
  fi
fi
TMP="$HOME/scratch/import-$$"
rm -rf "$TMP"; mkdir -p "$HOME/scratch"

# ---------- bring the code in ----------
case "$KIND" in
  url)
    if ! GIT_TERMINAL_PROMPT=0 git clone -q "$SRC" "$TMP" 2>/dev/null; then
      [ "$INTERACTIVE" = 1 ] || die "could not clone $LABEL (private or unreachable). From a chat: ask the owner to copy the repo folder or a bundle into ~/import/, or to run this script in an SSH terminal, where it can ask for a token."
      echo "Could not clone $LABEL anonymously. For a private GitHub repo, paste a fine-grained token with read access"
      echo "to that repo only (Contents: read), or press Enter to stop."
      read -rsp "GitHub token (input hidden): " GT </dev/tty; echo >&2
      [ -n "$GT" ] || die "no token; nothing imported"
      GHOST="$(sed -E 's#^https://([^/]+)/.*#\1#' <<<"$SRC")"
      git config --global credential.helper store
      printf 'protocol=https\nhost=%s\nusername=x-access-token\npassword=%s\n\n' "$GHOST" "$GT" | git credential approve
      unset GT; chmod 600 "$HOME/.git-credentials" 2>/dev/null || true
      git clone -q "$SRC" "$TMP" || die "the clone failed with the token too"
    fi ;;
  bundle|git)
    git -c safe.directory='*' clone -q --no-hardlinks "$SRC" "$TMP" || die "could not clone from $SRC"
    for br in $(git -C "$TMP" for-each-ref --format='%(refname:lstrip=3)' refs/remotes/origin); do
      [ "$br" = HEAD ] || git -C "$TMP" show-ref -q --verify "refs/heads/$br" || git -C "$TMP" branch -q "$br" "origin/$br"
    done
    git -C "$TMP" remote remove origin ;;
  plain)
    mkdir -p "$TMP"
    /usr/bin/python3 - "$SRC" "$TMP" <<'EOF'
import os, re, shutil, sys
src, dst = sys.argv[1:]
JUNK = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".DS_Store", "Thumbs.db"}
SECRET = re.compile(r"^(\.env(\..*)?|.*\.pem|.*\.key|id_(rsa|ed25519|ecdsa).*)$", re.I)
skipped = []
for root, dirs, files in os.walk(src):
    dirs[:] = [d for d in dirs if d not in JUNK]
    rel = os.path.relpath(root, src)
    for f in files:
        if f in JUNK or (SECRET.match(f) and not f.endswith((".example", ".sample"))):
            skipped.append(os.path.join(rel, f)); continue
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        shutil.copy2(os.path.join(root, f), os.path.join(dst, rel, f))
if skipped:
    print("import-project: not copied (secret-like or junk): " + ", ".join(skipped[:20]))
EOF
    git -C "$TMP" init -q -b main
    git -C "$TMP" add -A
    git -C "$TMP" commit -q -m "Import $LABEL (no earlier history)" ;;
esac
[ "$(git -C "$TMP" rev-list --count HEAD 2>/dev/null || echo 0)" -gt 0 ] || die "the source has no commits"
rm -rf "$W"; mv "$TMP" "$W"
grep -qxF '.worktrees/' "$W/.git/info/exclude" 2>/dev/null || echo '.worktrees/' >> "$W/.git/info/exclude"
echo "imported $LABEL: $(git -C "$W" rev-list --count HEAD) commits, $(git -C "$W" ls-files | wc -l) files"

# ---------- what stayed behind in a local repo folder ----------
mkdir -p "$V/raw/predecessor"
LB="$V/raw/predecessor/not-imported.md"
if [ "$KIND" = git ]; then
  /usr/bin/python3 - "$SRC" "$LB" "$TODAY" <<'EOF'
import os, subprocess, sys
src, out, today = sys.argv[1:]
r = subprocess.run(["git", "-c", "safe.directory=*", "-C", src, "status", "--porcelain", "--ignored", "--untracked-files=normal"],
                   capture_output=True, text=True)
rows = []
for line in r.stdout.splitlines():
    tag, path = line[:2], line[3:].strip('"')
    if tag not in ("??", "!!"):
        continue
    p = os.path.join(src, path)
    size = 0
    for root, _, files in os.walk(p) if os.path.isdir(p) else [(os.path.dirname(p), [], [os.path.basename(p)])]:
        for f in files:
            try: size += os.path.getsize(os.path.join(root, f))
            except OSError: pass
    rows.append((path, "untracked" if tag == "??" else "ignored", size))
L = ["---", "title: Not imported", "type: research", "status: active", "owner: manager", f"updated: {today}",
     "summary: \"Files in the source folder that git did not carry over - data, caches, local settings; decide what moves.\"",
     "tags: [import, predecessor, generated]", "---", "# Not imported", "",
     f"_Generated by `import-project.sh` from `{src}`. Only committed files were imported. These stayed behind._", ""]
if rows:
    L += ["| Path | Kind | Size |", "|---|---|---|"]
    L += [f"| `{p}` | {k} | {s/1e6:.1f} MB |" for p, k, s in sorted(rows, key=lambda x: -x[2])[:80]]
    L += ["", "Data the project needs (inputs, assets) belongs in `~/data/` (outside git) or must be re-created; ask the owner. "
          "Personal files, local settings and anything secret stay out."]
else:
    L.append("Nothing: the folder was clean.")
open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
print(f"import-project: {len(rows)} untracked/ignored path(s) listed in raw/predecessor/not-imported.md")
EOF
fi

# ---------- survey, notes, status, team rules ----------
/usr/bin/python3 "$S/import-survey.py" --snapshot
[ -z "$NOTES" ] || /usr/bin/python3 "$S/import-survey.py" --notes "$NOTES"
sed -e "s|{{IMPORT_FROM}}|$LABEL|g" -e "s|{{IMPORT_DATE}}|$TODAY|g" "$S/templates/00-status-onboarding.md" > "$V/00-status.md"
{
  printf -- '---\ntitle: Team rules (to merge)\ntype: system\nstatus: active\nowner: manager\nupdated: %s\n' "$TODAY"
  printf 'summary: The template team rules and team table; the takeover merges them into workspace/AGENTS.md.\n'
  printf 'tags: [system, import]\n---\n\n'
  cat "$S/templates/team-rules.md"
} > "$V/system/team-rules.md"
/usr/bin/python3 "$S/vault-index.py" "$V" >/dev/null
"$S/vault-log.sh" manager ingest "Imported $LABEL into workspace/ ($KIND); phase onboarding, takeover next" "raw/predecessor/inventory" >/dev/null
if [ -d "$HOME/.git" ]; then
  "$S/vault-commit.sh" manager "import: $LABEL" vault/raw/predecessor vault/00-status.md vault/system/team-rules.md vault/index.md vault/log.md >/dev/null || true
fi
echo "Next: the Manager takes the project over (project-takeover skill). Source left in place: $SRC"
