# tour.json (web)

`tour/web/tour.mjs` runs from the kit (nothing is copied into the app) with Playwright resolved from the app's own
`node_modules`. Same steps and output as `tour/ios/SCHEMA.md`; differences only:

```json
{
  "device": "iPhone 13",                          // a Playwright device name (viewport, touch, user agent)
  "start": "/",                                   // first page of every fixture
  "baseURL": "http://localhost:3000",             // BASE_URL in the environment wins
  "localStorage": {"age-ack": "1"},               // set before any page script runs
  "geolocation": {"latitude": 40.73, "longitude": -74.0},   // optional; absent = location never granted
  "routes": [{"url": "**/rest/v1/bars*", "file": "fixtures/bars.json", "status": 200}],  // recorded API answers
  "fixtures": [{"name": "signed-in", "localStorage": {}, "routes": []}],   // optional; flows run once per fixture, fresh browser context each
  "flows": [{"name": "home", "steps": [
    {"goto": "/rankings"},                        // web only: open a path
    {"waitFor": "Share my location"},             // runs BEFORE this step's tap, as on iOS: wait in the step after a tap
    {"tap": "social-tab-plans"}                   // data-testid, id, aria-label, or a button/link/tab's exact accessible name
  ]}]
}
```

`background` steps are iOS-only (a problem on the web). `gate-perf` is read from `[data-testid="gate-perf"]`
(`aria-valuetext`, `aria-label` or text). `idleMs` is the click call; `settleMs` is how long one frame plus one task
took 0.8 s later (a long task or deferred work delays it). An uncaught page error is a tour problem.

The `.tree.txt` is the DOM written in XCUITest's `debugDescription` shape (types Button, Link, Switch, TextField,
PopUpButton, Image, Cell, StaticText, Other; identifier = `data-testid` or `id`; frames in viewport points), so
`rules/rules.py` and the reader treat both platforms alike. Hidden elements (`display:none`, `visibility:hidden`,
`opacity:0`, `aria-hidden`) are left out; off-screen ones stay in with their real frames.

Gate job: `uses: …/gate.yml@<sha>` with `platform: web`, `runner: ubuntu-latest`, `prepare` (install, browsers,
production build), `serve` (start the server in the background), `base_url`, and optionally the `APP_ENV` secret
(dotenv lines written to `.env.local` before prepare).
