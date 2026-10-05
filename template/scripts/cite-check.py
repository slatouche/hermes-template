#!/usr/bin/python3
"""Check a research page's claims against their sources, with no model: does each quoted sentence really
appear on the page it cites? Deep-research tools often cite pages that don't say what they're cited for;
this catches that before the owner reads it.

  cite-check.py <vault page.md>

The page keeps a claims table with these columns (more columns are fine):
  | # | Claim | Source | Quote |
Source holds the URL; Quote holds a short exact sentence copied from that page. Each row comes back as
VERIFIED (the quote is on the page), NOT FOUND (it isn't: fix the claim or the quote), or COULDN'T FETCH
(a login, a block or a page built by JavaScript: check it with the browser tool and say so in the page).
Exit code 1 if anything is NOT FOUND.
"""
import difflib
import gzip
import html
import re
import sys
import urllib.request
import zlib

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_cache = {}


def norm(s):
    s = html.unescape(s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s'\-.,%:/]", " ", s)).strip().lower()


def page_text(url):
    if url in _cache:
        return _cache[url]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en", "Accept-Encoding": "gzip, deflate"})
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read(8_000_000)
            enc = (r.headers.get("Content-Encoding") or "").lower()
            if enc == "gzip" or body[:2] == bytes([0x1F, 0x8B]):     # some servers compress even when not asked
                body = gzip.decompress(body)
            elif enc == "deflate":
                body = zlib.decompress(body)
            raw = body.decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception as e:                       # noqa: BLE001 - every failure is reported, not raised
        _cache[url] = None, str(e)[:80]
        return _cache[url]
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    text = norm(re.sub(r"<[^>]+>", " ", raw))
    _cache[url] = (text, None) if len(text) > 200 else (None, "page has almost no text (JavaScript-built?)")
    return _cache[url]


def found(quote, text):
    q = norm(quote)
    if not q:
        return False
    if q in text:
        return True
    m = difflib.SequenceMatcher(None, text, q, autojunk=False).find_longest_match(0, len(text), 0, len(q))
    if m.size >= 0.8 * len(q):                   # most of the quote, word for word
        return True
    words = q.split()                            # same words in a short window (formatting differences)
    if len(words) >= 5:
        first = text.find(words[0])
        while first != -1:
            window = text[first:first + len(q) * 2]
            if sum(w in window for w in words) >= 0.9 * len(words):
                return True
            first = text.find(words[0], first + 1)
    return False


def rows(md):
    header, out = None, []
    for line in md.splitlines():
        if not line.strip().startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            low = [c.lower() for c in cells]
            if "source" in low and "quote" in low:
                header = low
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        d = dict(zip(header, cells))
        url = re.search(r"https?://[^\s)\]>|]+", d.get("source", ""))
        quote = d.get("quote", "").strip().strip('"“”').strip()
        out.append((d.get("#") or str(len(out) + 1), d.get("claim", "")[:60], url.group(0) if url else None, quote))
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: cite-check.py <page.md>")
    claims = rows(open(sys.argv[1], encoding="utf-8").read())
    if not claims:
        sys.exit("cite-check: no claims table (| # | Claim | Source | Quote |) in this page")
    bad = 0
    for n, claim, url, quote in claims:
        if not url or not quote:
            print(f"{n}. MISSING SOURCE OR QUOTE: {claim}")
            bad += 1
            continue
        text, err = page_text(url)
        if text is None:
            print(f"{n}. COULDN'T FETCH ({err}): {url}")
        elif found(quote, text):
            print(f"{n}. VERIFIED: {claim}")
        else:
            print(f"{n}. NOT FOUND on {url}: \"{quote[:80]}\"")
            bad += 1
    print(f"cite-check: {len(claims)} claims, {bad} to fix")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
