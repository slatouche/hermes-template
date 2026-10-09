# Verifying a page that updates itself without reloading

When a page claims "changes arrive on their own while you look at it", the check has three parts, and
the first is the one that gets skipped: proving that **no reload happened**.

## Proving no reload

Plant a marker that only survives while the same document lives, and read the navigation facts:

```js
window.__probe = 'alive';
performance.getEntriesByType('navigation').length   // 1 = never navigated away
performance.timeOrigin                              // ms since this document started
performance.getEntriesByType('navigation')[0].type  // 'navigate' first, 'reload' after a reload
```

Then change the file the page watches, wait, and re-read all three: probe still `'alive'`, nav count
still 1, `timeOrigin` identical — the change arrived in place. Check what must be *preserved* too:
`window.scrollY`, the focused element, text already typed into an input.

Pitfalls:
- Asserting the new content appears proves nothing on its own — a reload shows the new content too.
  If the check would still pass after a reload, it is not a test of live updating. Assert the
  unchanged document facts as well as the changed content.
- A backgrounded tab hides the whole feature: read `document.hidden` first, and
  `cdp('Page.bringToFront')` before probing. A page whose script polls on a timer skips every tick
  while hidden, so it looks dead when it is fine (and a live-update check then reports a false fail).
- Keep the probe's own writes out of the watched file set, or your first write restarts the thing you
  are measuring.
- A stylesheet change shows up as a computed value on one element; an HTML change as text plus a
  preserved scroll position — assert the computed value, not the file contents.

## Test the fault path through to recovery

A watcher must be tested with a fault, not just with a good change:

1. Point a watched entry at something missing → expect **exactly one** reload
   (`navigation[0].type === 'reload'`, then the count stays put) and a visible line naming what could
   not be fetched.
2. Restore the cause **without touching the page** → the page must recover on its own: the change
   applies, the notice clears, `timeOrigin` is unchanged (so no second reload).

Step 2 is the one that catches a latch, and it is the step people skip. A page that needs a manual
reload to recover from a fault has broken the very promise that justified building it — the user
never has to reload — and a check that stops after step 1 reports PASS for a dead page.

Mechanism behind the usual latch: a poll loop that `return`s on the first failed fetch, when the
list of files to watch is itself stored in one of the files being watched — one bad entry stops the
loop for good. The fix is to apply each healthy entry independently and clear the notice on a clean
pass, not to widen the timeout.

## Reporting

Give the command, the change made, and the three facts (probe, navigation count, `timeOrigin`) for
both the change and the recovery, plus the fault notice text. "Probe alive, navs 1, timeOrigin
unchanged, computed outline became rgb(255,0,0)" beats "the page updated".
