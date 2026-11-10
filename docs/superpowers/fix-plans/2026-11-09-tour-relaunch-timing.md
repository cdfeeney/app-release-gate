# Fix plan: a per-flow relaunch resets the app's timing counters (Codex r1)

## 1. The finding

🔴 (validated). Task 2 (344be96) lets a flow relaunch the app (`terminate()` + `launch`). The app's `gate-perf`
counters (`n`, `sync`) live in the app process, so a relaunch starts them again at zero. `rules.py`
`rule_app_timings` resets its state (`last_sample`, `last_sync`) only when the fixture prefix of `step` changes
(`rules.py:503-504`). After a relaunch inside the same fixture:
(a) `rules.py:514` reads the fresh low `n` as `<= last_sample` and fails the tap as "stale" (a false failure);
(b) `rules.py:507` gives `maxFirstAppMillis` only while `last_sample is None`, so the cold first tap after the
relaunch is judged on the steady `maxAppMillis` and lands in the steady median.

## 2. Every caller, file and data path

- Produced: `Tour.swift` `appTimings(in:)` (identifier `gate-perf`, ~line 231) → `entry["app"]` in the tap recorder
  (`Tour.swift:225`). Process restarts: `testTour` fixture loop (initial `launch`, line 91; relaunch, lines 100-102);
  `launch(_:arguments:)` retries (lines 124-135) happen before any tap of that launch.
- Written: `taps` array → `taps.json` (`Tour.swift` `write(json: taps, ...)`). Unrevealed taps
  (`Tour.swift:167, 192, 201`) are written without timings and skipped by the rules (`revealed is False`).
- Consumed: `rules.py` `rule_app_timings` only (`last_sync`, `last_sample`, `first_budgets`, `afterBackground`,
  lines 479-533), called from `rules.py:670`. Tests: `test_rules.py` `test_clean_tour_passes` (afterBackground,
  line 151), `test_app_timings_are_the_apps_own_clock` (stale, fresh_launch, synced, blind, first budgets,
  lines 159-202), `ALL_RULES` bad-tour (line 61/125).
- New marker `afterLaunch: true` vs `afterBackground`: `afterBackground` is a dict (seconds, resumeMs) that adds a
  check (sync must not rise); `afterLaunch` is a bare flag that removes state (the rule forgets `last_sample` and
  `last_sync`, exactly as on a fixture change). Both are one-shot: set by an event, consumed by the next recorded
  (revealed) tap. Unlike `pendingBackground`, `pendingLaunch` is NOT cleared at `run` start: `run` is called right
  after the relaunch, so clearing there would erase the marker before any tap. It is cleared at fixture start instead.

## 3. What could break

- A relaunched flow with no taps: the marker carries to the next flow's first tap. That is correct: the next flow
  either runs in the same process (its first tap is still the first of that launch) or relaunches again (marker set
  again). A fixture change clears it (and the rules reset on a fixture change anyway).
- Initial launch: must not set the marker (the fixture change already resets the rules); only the relaunch branch
  sets it, only on success.
- Manifests with no flow `launchArguments`: the relaunch branch never runs, `pendingLaunch` stays false, taps.json
  is byte-identical in shape; the rules never see the key.
- `afterBackground` on the first tap after a relaunch: `last_sync` is None, so the rule fails closed ("not
  readable on both sides"), the same as the first tap of a fixture today. Before this fix it compared against the
  dead process's count, which proved nothing. Accepted.
- The marker on a non-timed tap: the reset still happens there; the next timed tap still sees `last_sample is None`
  and gets the first budget. Correct.

## 4. Same rule, other inputs

Rule: every app-process restart resets the timing rule's state and gets the first-launch budget.
- Fixture change (initial launch per fixture): already handled by the step-prefix reset; existing test
  `fresh_launch` covers it.
- Per-flow relaunch: this fix; tests (i)-(iii) below.
- Launch retries inside `launch(_:arguments:)`: happen before any tap of that launch, so no tap sees the old
  process; nothing to test.
- `background` step (Home, `activate()`): the same process resumes; counters are not reset and must not be
  (the `afterBackground` sync check depends on that). If iOS killed the app while away, `activate()` would start it
  cold: out of scope (see 6).

## 5. Failing tests first

In `test_rules.py` next to `fresh_launch` (inside `test_app_timings_are_the_apps_own_clock`, already registered
in the `__main__` call list):
(i) a second timed tap in the same fixture with `n` lower than the first and `afterLaunch: True` → no app-timings finding;
(ii) the same tap without the marker → still fails as stale (the marker is what excuses it);
(iii) with `maxFirstAppMillis: {"tap": 1500}`, the post-relaunch tap at 1200 ms (between 300 and 1500) → passes.
`test_bad_tour_fails_every_rule` must still report `app-timings`.

## 6. What's out of scope

- The app being killed in the background during a `background` step (an `activate()` cold start): no marker; not
  seen on any run.
- An app crash mid-flow: XCUITest does not relaunch it; later taps fail on missing elements.
- Prefixing the relaunch problem message with the fixture name (noted in the Task 2 report).
