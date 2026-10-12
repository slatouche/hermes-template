# Writing checks that prove something

The rules behind `SKILL.md` step 3, with the reasons. Each one came from a check that passed while the owner still hit the bug.

## Before it goes in the card
- **Run it yourself and note what it returns now.** A wrong port, path or route sends the worker chasing a phantom failure, or passes a check that proves nothing.
- **Confirm the harness can run it**, the input as well as the observation. A drag needs a real pointer, which `ui-check.sh` doesn't do (prove a drag in the app's own tests, or with the browser tool's real pointer); a flat `--js` sweep can't dispatch one. A check the harness can't perform comes back as a defect and costs a round: name the route that works, or card the capability into the harness first.
- **Make it able to fail.** Run it against the blocked case (a transparent cover over the control, the build before the fix) and watch it report FAIL.
- Once a card is running its body can't be edited (a comment is the only correction, and the worker may never read it), so get the checks right before dispatch.

## Real input, not scripted changes
A control the owner clicks or types into is proved by a real pointer press/release at its centre and real key events, then asserting focus moved and the text arrived (`ui-check.sh --click '<sel>' --url <url> --expect '<js>'`, `--type '<sel>' '<text>' --url <url>`). Assigning `.value`, calling `.click()` or reading the DOM after a scripted change certifies a page the owner can't use: a handler that cancels the pointer-down, or an element sitting over the control, is invisible to a script. Recipes: `real-input-verification.md`.

## The owner's view, not yours
A layout complaint ("missing", "hidden", "looks wrong") is reproduced at 1280, 1100, 900 and 760 px before anything changes, and the card carries those numbers. A control strip anchored to one edge overflows off-screen on a narrower window: present in the DOM at your width, gone at theirs. The style a note carries is as the owner's browser rendered it (an extension like Dark Reader changes it); when it disagrees with the page, trust the page.

## A page that updates itself
New content appearing proves nothing: a reload shows it too. Plant a probe (`window.__probe='alive'`), change the watched file, and assert the probe survived, the navigation count is still 1 and `performance.timeOrigin` is unchanged. Then break what it watches and restore it: one reload and a notice, then recovery on its own with no second reload. Recipe: `live-update-verification.md`.

## Cheapest first
A colour, size, gap, count, position or overflow is a **number**: read it from the DOM or computed style in one call. A screenshot handed to `vision_analyze` costs 30-60 s, and on a vision-capable main model the image rides every later call of the session. Keep looks for what only a look answers ("does this balance?"), once, on the finished change, cropped to what changed.

## Never through a real channel, never behind another card
- **A test of the design view runs on a throwaway copy**, never the owner's: `design-view.py` on a spare port with a copy of the layer and `--no-cards` (and `DV_ASSETS` for changed page files). A note sent to the owner's design view is real work on their design.
- **A check that needs a card** (to exercise blocked, review or answer states) creates it on the **`rig` board**, blocked at creation: `HERMES_KANBAN_BOARD=rig hermes kanban create "<title>" --assignee <bot> --initial-status blocked`. Nobody is subscribed there (`hermes kanban notify-list <id>` → no subscriptions), so it can't ring the owner. Close it when the check is done.
- **A check never waits on another card** (sending a real note, dispatching a bot): that serialises it behind a whole second card cycle. Fake the upstream state (write the record the code reads, call the endpoint with a fixture); prove the real cross-card path once, in its own card.
- A test round is a card too: close it as part of the check (`hermes kanban complete <id> --force`) and withdraw the note it came from, or it keeps the bot's only seat.

