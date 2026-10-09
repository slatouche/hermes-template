# Real-input verification of a web control

A control the user clicks or types into is only proved usable by driving it the way a person does.
Scripted changes (`el.value = "x"`, `el.click()`, `el.focus()`) bypass hit-testing and the event
pipeline, so they pass on controls a person cannot touch. Use this whenever a check has to show that
"the user can use this box / this button".

## Order of work

1. **Bring the tab to the front** — `cdp('Page.bringToFront')`. A backgrounded tab reports
   `document.hidden === true`, and a page whose script polls on a timer (interval fetch, live chip,
   repaint loop) silently skips every tick, so the page looks empty or broken when it is fine. Read
   `document.hidden` before suspecting the page.
2. **Reach into the shadow root.** `document.elementFromPoint()` returns the shadow *host* for
   anything inside a shadow root, and comparing it to an inner element is always false — it cannot
   tell you what is on top. Use the root's own view:
   ```js
   const host = [...document.querySelectorAll('*')].find(e => e.shadowRoot);
   const root = host.shadowRoot;
   const ta = root.querySelector('.my-input');
   root.elementFromPoint(x, y) === ta   // what is really on top at that point
   root.activeElement === ta            // what holds focus inside the shadow root
   ```
   A plain `document.querySelectorAll('.overlay-box')` returns `0` for anything inside that root, so
   a check written that way reads an empty page and reports the control missing while it is on
   screen. To see what is stacked over the control, walk every descendant and list the ones whose box
   contains the point, with their `pointer-events`, `z-index` and `position`.
3. **Click it for real**, in CSS pixels from `getBoundingClientRect()`, then confirm focus moved:
   ```python
   cdp("Input.dispatchMouseEvent", type="mouseMoved", x=cx, y=cy)
   cdp("Input.dispatchMouseEvent", type="mousePressed", x=cx, y=cy, button="left", clickCount=1)
   cdp("Input.dispatchMouseEvent", type="mouseReleased", x=cx, y=cy, button="left", clickCount=1)
   ```
   Never infer that a click landed — assert `activeElement` changed, then read the value back.
4. **Type for real.** Per character, `cdp("Input.dispatchKeyEvent", type="keyDown", text=ch,
   unmodifiedText=ch)` then the matching `keyUp`; or `cdp("Input.insertText", text="...")` once the
   control has focus. Read the value back and report it.
5. **Prove the check can fail.** Cover the control with a transparent full-screen element (or run
   the check against the build before the fix) and confirm it reports FAIL. A check that passes on a
   blocked control proves nothing and will certify the next broken page too.

## A drag is its own gesture

A drag handler usually arms on `pointerdown` and only begins moving after the pointer has **moved**,
so one jump from A to B can be ignored and a click (down and up in place) is not a drag at all. Send
several real moves:

```python
cdp("Input.dispatchMouseEvent", type="mouseMoved", x=x0, y=y0)
cdp("Input.dispatchMouseEvent", type="mousePressed", x=x0, y=y0, button="left", clickCount=1)
for x, y in steps:      # a handler that needs movement before it arms sees real movement
    cdp("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, button="left", buttons=1)
cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x1, y=y1, button="left", clickCount=1)
```

Assert the effect, not the gesture, and take two readings — position alone misses the usual faults:

- **Size unchanged.** Width and height before and after. A box that stretches as it is dragged looks
  correct in every position check and is the fault a user actually reports.
- **Anchored to the edge.** Express the new place as a gap — `innerWidth - rect.right`,
  `innerHeight - rect.bottom` — never a bare `x`. Then **resize the viewport and read the gaps
  again**: a box that remembers a pixel from the left drifts, collides with edge-pinned neighbours
  and can hang off the screen when the window narrows, while a gap that holds at every width is the
  fix actually landed.
- **The move persisted.** Re-read after a reload if the placement is stored: a drag that is not saved
  is forgotten the next time the page opens.

If the flat check harness cannot dispatch pointer events, the drag has to run in a real browser
session — say which route a card should use rather than writing a check that cannot perform its own
input.

## Why a click can be swallowed

If the click does not land and nothing is stacked over the control, look for a handler that cancels
its default. Dispatch a cancelable event and read the flag:

```js
const ev = new PointerEvent('pointerdown', {bubbles: true, cancelable: true, composed: true,
                                           clientX: x, clientY: y, pointerId: 1, isPrimary: true,
                                           pointerType: 'mouse', button: 0});
el.dispatchEvent(ev);
ev.defaultPrevented;   // true -> the control never takes focus, so a person cannot type
```

`preventDefault()` on `pointerdown`/`mousedown` stops the focus that a normal click would give, so
typing afterwards does nothing even though the control is visibly there and `readOnly` is false.

Run the same probe on a sibling control that does work: the difference between `true` and `false`
locates the fault in one read.

The usual cause is a page-wide `pointerdown`/`mousedown` handler that cancels the event to keep
clicks off the content beneath it, and keeps a **hand-written list of its own panels** to exempt. A
panel added later and left off that list has every click on it cancelled — it reads perfectly in the
DOM and is dead to a person. Fix the list's shape (treat everything the component owns as its own
UI, minus the layers that must sit under the pointer), not just the missing entry: the next panel
will otherwise repeat the bug.

## Reporting

Give the command, the real input sent, what changed (focus, value, state), and the failing run
against the blocked case. "Real click focused the box; real keys typed; value read back as `hello`"
beats "the box works". For a drag, report the size that did not change and the edge gap before and
after a resize.