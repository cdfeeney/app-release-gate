# app-release-gate

One release gate for every app: a build reaches TestFlight or production only after a machine walked
it with real data, deterministic rules checked what it showed, and a reader who never saw the code
judged the screenshots. The session that wrote the code cannot satisfy any of the three.

Why: tests written from the code by the same author, reviews that read code, and "green CI" let
obvious on-screen errors reach the owner's phone (ConorHealth builds 34–39, NextBar staging-7).
This gate looks at what a person sees, with their real data, and refuses the upload otherwise.

## Parts

| Part | Where | Generic? |
|---|---|---|
| Gate workflow (tour → rules → reader → verdict) | `.github/workflows/gate.yml` (reusable) | yes |
| Tour: XCUITest that follows a manifest, screenshots every stop, dumps the accessibility tree, records whether each tap changed the screen | `tour/ios/Tour.swift`, copied into the app's UI test target unchanged | yes (iOS); a Playwright tour for web uses the same output format |
| Rules: deterministic checks over the tour output | `rules/rules.py` (+ `test_rules.py`) | yes; per-app patterns in `rules.json` |
| Reader: blind screenshot review by Claude, fixed JSON verdict | `reader/core.md`, `reader/run.py` | yes; per-app persona in `profile.json` |

## Rules (what the owner kept finding on the phone)

- `count-matches-rows`: a stated count ("0 of 16") equals the rows shown under it (on screens the tour scrolled
  to the bottom; a single screenshot cannot show every row)
- `same-count-everywhere`: the same titled item states the same total on every screen. A count pattern with a
  `(?P<title>)` group carries its title ("Daily mobility (5 min) · 0 of 4 done"); one without takes the StaticText
  just before it on the same row, for two-line headers ("Daily mobility (5 min)" / "5 min · 0 of 6"); a count
  line with no title line beside it is itself a finding
- `no-duplicate-titles`: no two blocks on one screen share a title
- `durations-in-minutes`: 60 s or more is never shown in seconds
- `no-stale-week`: no "week N" text for a week other than the fixture's; progression prose ("from week 3") passes
  only through an explicit `weekAllow` pattern
- `rows-reachable`: every row is fully visible above any pinned bar at some scroll position; checked only on
  screens the tour scrolled to the bottom (`scrollToBottom` steps in `tour.json`), since a single screenshot
  legitimately has rows below the fold
- `content-in-bounds`: elements whose identifier matches `inBoundsIdentifiers` (photos, cards) stay inside the window's
  left and right edges (NextBar 2026-10-18: a photo spilled past its chat bubble and the screen; the reader passed it).
  Off unless configured, since a carousel legitimately overhangs
- `controls-change-screen`: every tapped control changed something
- `taps-respond`: every tap is answered within `maxTapMillis` (default 1500). The tour records `idleMs` per tap, the
  time XCUITest's tap call took, and that call returns only when the app is idle again, so a main-thread stall is
  inside it; and `settleMs`, the idle wait a harmless probe tap met 0.8 s later, so work the app deferred past the
  tap (a debounced write) counts too. The larger of the two is judged. (`ms`, until the tree first differed, includes
  one tree snapshot and is only the fallback for older tours.)
- `app-timings`: the app's own clocks. After every tap the tour reads an element with identifier `gate-perf` whose
  value reads `tap=123 write=4 sync=1 n=7` (the app's tap-to-idle time, its last write, how many full syncs it has
  run, how many tap measurements it has completed) into the tap's `app` dict. XCUITest's idle wait includes
  animations and about half a second of harness overhead, so it cannot tell a 100 ms tick from a 600 ms one; the app
  can. Each key in `maxAppMillis` has its own budget (the first timed tap of each launch may have its own in
  `maxFirstAppMillis`, so a known first-change cost is budgeted in the open rather than hidden in a loose general
  budget); a shared simulator freezes for seconds now and then, so up to `appTimingOutliers` taps per run (default 1)
  may exceed a budget, while a second one or a median over the budget is the app's own lag; a tap whose identifier
  matches `appTimedIdentifiers` must carry
  every budgeted key and an `n` that advanced since the last timed tap of that launch (a stale reading is the previous
  tap's number); and `sync` must be readable on both sides of a `background` step and must not rise across it (an
  unlock between sets must never run a sync). The rule is off when neither key is configured.
- `instruction-not-live`: instruction text is never a tappable item
- `forbidden-text`: `Optional(`, `nil`, `NaN`, placeholders
- `forbidden-identifiers`: controls that must never be on screen, by accessibility identifier (per-side rows, in-app
  hold timers, a weight-chip grid). `forbiddenText` and `forbiddenIdentifiers` also take a per-fixture list under
  `"fixtures": {"<name>": {...}}`, for a control that is wrong only with that fixture's data (Find rows on an exercise
  whose weight the fixture's history already knows)

- `no-overlapping-text` (opt-in, `overlapCheck: true`): no two texts drawn over each other at one stop (Sunday
  2026-10-18: a native sheet bar's title was painted over the screen's own title and close button, "the top gets cut
  off"). Content scrolled under a floating tab bar overlaps in the tree too, so `overlapAllow` exempts such text
  (the bar's labels) and the rule stays off until an app opts in

Every bug an owner confirms becomes one more rule here, and then applies to every app.

## Add an app (four files + one workflow job)

1. Copy `tour/ios/Tour.swift` into the UI test target and add it to that target in the Xcode project. Never edit the copy; the gate checks it matches.
2. Create `<UITests>/Gate/` with:
   - `tour.json` – launch arguments, fixture env key, fixtures (real data, scrubbed), flows and steps. Schema: `tour/ios/SCHEMA.md`.
   - `rules.json` – patterns for this app's identifiers and texts. Example: `rules/rules.example.json`.
   - `profile.json` – `user`, `hates`, `context` for the blind reader.
   - `fixtures/*.json` – real sessions/data with private fields scrubbed.
   Keep only `.swift`/`.json` in here if the app exports an allowlisted build copy.
3. In the app's release workflow add the `gate` job (see the header of `gate.yml`) and make the upload/deploy job `needs: [tests, gate]` with `if: needs.gate.result == 'success' && needs.gate.outputs.verdict == 'PASS'`. Remove any input that lets a session approve its own upload.
4. The repo (or the public build copy) needs the `CLAUDE_CODE_OAUTH_TOKEN` secret for the reader. An app whose source
   reaches the runner encrypted (Sunday's public build copy) also sets `PREPARE_SECRET`: the prepare shell is the only
   step that sees it, and uses it to decrypt and generate the project before the tour builds.

Write `tour.json` from the design's list of screens and controls, not from the code.

## Running pieces locally

```
python3 rules/test_rules.py                       # self-check
python3 rules/rules.py --tour <downloaded tour dir> --config <rules.json> --manifest <tour.json>
python3 reader/run.py --tour <dir> --profile <profile.json> --rules-report <report.json>   # needs claude + token
```

## Claim format after a gated run

```
Tests: <n> passed
Tour: <n> screens captured, <fixtures>
Rules: PASS | FAIL (<findings>)
Blind reader: PASS | FAIL (<findings>)
Only a phone can prove: <camera, sync, real-device speed, ...>
```

Anything without a line is "not checked". "Compiles" is never "good".

## Limits

Hardware (camera), real-device performance, sync and anything not in a fixture are not covered;
say so in every TestFlight note. The reader is an LLM: its findings are advisory on top of the rules,
but its PASS is required and it cannot be written by the session that built the app.
