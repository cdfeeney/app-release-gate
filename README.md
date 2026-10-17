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

- `count-matches-rows`: a stated count ("0 of 16") equals the rows shown under it
- `same-count-everywhere`: the same titled item states the same total on every screen
- `no-duplicate-titles`: no two blocks on one screen share a title
- `durations-in-minutes`: 60 s or more is never shown in seconds
- `no-stale-week`: no "week N" text for a week other than the fixture's
- `rows-reachable`: every row is fully visible above any pinned bar at some scroll position
- `controls-change-screen`: every tapped control changed something
- `instruction-not-live`: instruction text is never a tappable item
- `forbidden-text`: `Optional(`, `nil`, `NaN`, placeholders

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
4. The repo (or the public build copy) needs the `CLAUDE_CODE_OAUTH_TOKEN` secret for the reader.

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
