# tour.json

```json
{
  "launchArguments": ["--test-store", "{uuid}"],        // "{uuid}" is replaced per launch
  "launchEnvironment": {"SOME_FLAG": "1"},              // optional
  "fixtureEnvKey": "COACH_TEST_SESSION",                // env var that receives each fixture's JSON text
  "fixtures": [                                         // optional; flows run once per fixture
    {"name": "wed", "file": "fixtures/wed.json", "setDateKeyToToday": "date", "week": 2}
  ],
  "flows": [
    {"name": "today", "steps": [
      {"waitFor": "tab-Today"},                         // wait up to 15 s for an identifier
      {"tap": "tab-Today", "expectChange": false},      // tap by identifier (reveals by scrolling first)
      {"scrollToBottom": true, "shot": "today"}         // screenshot at every scroll position until stable
    ]},
    {"name": "session", "steps": [
      {"tap": "today-coach-start"},                     // default expectChange: true
      {"scrollToBottom": true, "shot": "session"},
      {"tapMatching": "^coach-select-weight-b\\d+-e\\d+-p0$", "optional": true},  // first identifier matching a regex, searched over every capture of this flow so far (lazy lists drop off-screen rows), then the live tree; the tour scrolls back to reveal it
      {"shot": "after-find"},                           // single screenshot
      {"typeText": "45"},                               // types into the focused field (use after a tap)
      {"swipe": "down"},                                // one slow swipe up|down
      {"sleep": 1.0}
    ]}
  ]
}
```

Output per stop: `NNN-<fixture>-<flow>-<name>.png` and `.tree.txt` (the accessibility tree), listed in
`index.json`; every tap in `taps.json` with `changed: true|false` and `ms` (milliseconds from before the tap until the
tree first changed; the tap call itself waits for the app to go idle, so a main-thread stall is counted. It is an
upper bound on responsiveness, not proof that the intended result appeared: an early spinner counts as a change);
`summary.json` with problems (missing
identifiers, taps that changed nothing). A non-optional problem fails the tour.

Paths: `TOUR_PATH`/`TOUR_OUT` from the environment (xcodebuild passes `TEST_RUNNER_TOUR_PATH` as
`TOUR_PATH`), else `Gate/tour.json` and `Gate/out` beside `Tour.swift`.

## XCUITest traps (each one cost a 30-minute runner round once)

- An identifier on a container that is not an accessibility element propagates to every child; put
  `.accessibilityElement(children: .contain)` before the identifier on rows and cards. Never put an
  identifier on a TabView tab root.
- An identifier on a ScrollView surfaces as type ScrollView; icon-only buttons with
  `.accessibilityElement(children: .ignore)` surface as Other unless given `.isButton`.
- Toggles: the switch is a nested child. Lazy lists: rows below the fold are absent from the tree, which
  is why the tour scrolls to the bottom and the rules take the union of all stops.
- A pinned `safeAreaInset` bar covers the bottom of a scroll view; list every pinned bar's identifier in
  `rules.json` `pinnedBars` so `rows-reachable` can see it.
- `Text` is a staticText, not a button. Taps land on the centre of the frame; a row with a Spacer needs
  `.contentShape(Rectangle())`.
- `app.terminate()` is SIGKILL: anything not yet persisted is lost; flush before the next flow if a
  flow depends on saved state.
