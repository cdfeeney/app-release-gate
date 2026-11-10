# Gate kit: Places key pass-through, per-flow launch arguments, `contained-in` rule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the release gate's iOS tour build receive app build settings (so Next Bar's tour shows real Google photo widgets), let one tour flow relaunch the app with extra arguments (an empty account), and add a rule that fails when a named element is missing from, or sticks out of, its container (the map card's bar name).

**Architecture:** Three small changes on the kit branch Next Bar pins (`nextbar-sheet-safe-clear`): a secret read in `gate.yml`'s tour step turned into `xcodebuild` arguments; a `launchArguments` field on a tour flow in `Tour.swift` that terminates and relaunches the app; a `rule_contained_in` in `rules/rules.py` driven by a `containedIn` list in the app's `rules.json`. Tasks K1–K2 ship first (job 0a); K3 waits for the real tree captured by Next Bar's first run with the key (job 0b).

**Tech Stack:** GitHub Actions reusable workflow (bash), Swift XCUITest (`Tour.swift`), Python 3 (`rules.py`, self-check script, no pytest).

**Spec:** `D:/harness-handoffs/specs/2026-11-09-nextbar-phone-pass-and-invite-design.md` §4 A1–A3, §7 steps 0–2 (copied into next-bar as `docs/superpowers/specs/2026-11-09-nextbar-phone-pass-and-invite-design.md`).

## Global Constraints

- Repo `D:/projects/app-release-gate`; base branch **`origin/nextbar-sheet-safe-clear`** (pinned by next-bar at 6df5a4a), never `main`. Start: `node ~/.claude/bin/job.mjs start kit-nextbar-places --repo D:/projects/app-release-gate`, then inside the worktree `git reset --hard origin/nextbar-sheet-safe-clear` (job.mjs branches off main; the reset puts the job on the right base). Finish: `git push origin HEAD:nextbar-sheet-safe-clear` (never `job.mjs finish`, which fast-forwards main), then `node ~/.claude/bin/job.mjs clean <worktree>`.
- Commit subjects carry the tier `[T1]` and every commit body a `Spec:` line naming the spec path above.
- The kit is generic: no Next Bar names in kit code or docs beyond the changelog line; the secret and the flow field are app-agnostic.
- `rules/test_rules.py` is the test runner: `python3 rules/test_rules.py` must end with `rules self-check: ok`. New tests are plain functions added to the call list at the bottom; new rule names go into `ALL_RULES` and the "bad tour" fixture must fail the new rule too.
- `tour/ios/Tour.swift` is copied verbatim into each app (`scripts/verify-copy.py` enforces it): keep it compiling under Swift 5 / iOS 17 simulators with no new imports.
- Codex review before the push: `node ~/.claude/bin/review-run.mjs --repo <worktree> --base origin/nextbar-sheet-safe-clear --spec <spec path>`.

## Review Focus

1. `APP_BUILD_SETTINGS` contains a value with spaces or `=` inside (e.g. `FOO=a=b`): the whole line must reach `xcodebuild` as one argument `FOO=a=b`, not split. Test in K1 step 1.
2. `APP_BUILD_SETTINGS` empty or unset: the tour command is byte-for-byte what it is today (no empty-string argument). Test in K1 step 1.
3. A flow with `launchArguments` followed by a flow without: the second flow must see the manifest's default arguments again (relaunch back), or the gate tours the wrong account. K2 step 3 + SCHEMA note.
4. `containedIn` container present on a stop but child element has `frame == None` (hidden/zero): must count as missing, not pass. Test in K3 step 1.
5. Container matched by two elements (e.g. `map.card` and `map.card.parked` both present): the child must be inside at least one; report once per stop. Test in K3 step 1.

---

### Task K1: `APP_BUILD_SETTINGS` → xcodebuild arguments in the tour step

**Files:**
- Modify: `.github/workflows/gate.yml` ("Run the tour" step, lines 109–138 at 6df5a4a)
- Create: `scripts/build-settings-args.sh` (the parser, so it is testable)
- Create: `scripts/test_build_settings_args.sh`
- Modify: `README.md` (one paragraph under the iOS caller section), `CHANGELOG`/header comment if the kit keeps one

**Interfaces:**
- Produces: `scripts/build-settings-args.sh` — reads the env var `APP_BUILD_SETTINGS` (dotenv-style lines `KEY=VALUE`, `#` comments and blank lines ignored, KEY matches `^[A-Za-z_][A-Za-z0-9_]*$`), prints each kept line NUL-separated on stdout; exit 0 always. Callers: `mapfile -d '' -t EXTRA < <(bash scripts/build-settings-args.sh)` then `xcodebuild ... "${EXTRA[@]}" test`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing test** `scripts/test_build_settings_args.sh` (bash, `set -euo pipefail`):
  - unset var → zero output bytes;
  - `APP_BUILD_SETTINGS=$'GOOGLE_PLACES_API_KEY=abc\n# note\n\nFOO=a=b c'` → exactly two NUL-separated items: `GOOGLE_PLACES_API_KEY=abc`, `FOO=a=b c`;
  - `APP_BUILD_SETTINGS='1BAD=x'` → zero items (invalid key dropped);
  - prints `build-settings-args: ok` at the end.
- [ ] **Step 2: Run it:** `bash scripts/test_build_settings_args.sh` → FAIL (`No such file` for the parser).
- [ ] **Step 3: Implement `scripts/build-settings-args.sh`** (≤ 15 lines: `while IFS= read -r line` over `printf '%s\n' "${APP_BUILD_SETTINGS-}"`, regex check `^[A-Za-z_][A-Za-z0-9_]*=`, `printf '%s\0' "$line"`).
- [ ] **Step 4: Run it:** `bash scripts/test_build_settings_args.sh` → `build-settings-args: ok`.
- [ ] **Step 5: Wire gate.yml.** In "Run the tour": add `APP_BUILD_SETTINGS: ${{ secrets.APP_BUILD_SETTINGS }}` to `env`; before `xcodebuild`, `mapfile -d '' -t EXTRA < <(bash .release-gate-kit/scripts/build-settings-args.sh)`; add `"${EXTRA[@]}"` between `CODE_SIGNING_ALLOWED=NO \` and `test`. Add to `on.workflow_call` a `secrets:` map with `APP_BUILD_SETTINGS: { required: false, description: "Optional. Dotenv lines of xcodebuild build settings for the tour build (e.g. an API key the app reads from Info.plist)" }` — callers with `secrets: inherit` keep working. Note: the kit's checkout path inside the caller's workspace is whatever the existing steps use for `rules.py` (`.release-gate-kit/`); use the same.
- [ ] **Step 6: Validate the YAML:** `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/gate.yml'))"` → no error (install PyYAML if missing: `pip install pyyaml`).
- [ ] **Step 7: README paragraph** (3 lines): what the secret is, the format, the iOS-only scope.
- [ ] **Step 8: Commit** `feat(gate): [T1] APP_BUILD_SETTINGS secret → xcodebuild build settings for the iOS tour build` with `Spec:` line.

### Task K2: per-flow `launchArguments` in `Tour.swift`

**Files:**
- Modify: `tour/ios/Tour.swift` (`Flow` struct ~line 25; the fixture loop ~lines 83–101; `launch(_:)` ~line 113)
- Modify: `SCHEMA.md` (flow fields)

**Interfaces:**
- Produces: tour.json flow field `"launchArguments": [String]` (optional). Semantics: before a flow that has it, the tour terminates the app and launches it with `manifest.launchArguments + flow.launchArguments` (+ the `{uuid}` substitution the launcher already does); before the next flow that lacks it (and at least one earlier flow had it), the tour relaunches with the manifest arguments alone. Screens, trees and taps are recorded exactly as for any flow.
- Consumes: nothing.

- [ ] **Step 1: Add the field** `var launchArguments: [String]?` to `Flow`.
- [ ] **Step 2: Track the current launch set.** In the per-fixture loop keep `var launchedWith: [String]` (the arguments of the live app). For each flow compute `wanted = manifest.launchArguments + (flow.launchArguments ?? [])`; if `wanted != launchedWith` → `app.terminate()`, `launch(app, arguments: wanted)`, `launchedWith = wanted`. The launcher gains an `arguments:` parameter; the first launch passes the manifest's.
- [ ] **Step 3: Relaunch failure is a problem, not a crash:** if the relaunched app does not reach any element within the launcher's existing timeout, `note("\(flow.name): relaunch with \(wanted) never came up")` and skip the flow's steps (the gate then fails on the problem).
- [ ] **Step 4: SCHEMA.md:** document `launchArguments` on a flow with the relaunch rule (one paragraph) and the caveat that a relaunch starts the app cold (sign-in flows must be repeated inside that flow).
- [ ] **Step 5: Compile check.** No Mac here: push the branch and let Next Bar's first `--ui` run (next-bar plan, Task N3) compile it; `verify-copy.py` also runs there. If it fails to compile, fix on this branch and re-pin.
- [ ] **Step 6: Commit** `feat(tour): [T1] a flow may set launchArguments; the tour relaunches the app for it and back` with `Spec:` line.
- [ ] **Step 7: Review + push (job 0a):** Codex review command from Global Constraints; fix 🔴s with fix plans; `git push origin HEAD:nextbar-sheet-safe-clear`; record the sha — next-bar Task N3 pins it.

### Task K3: `contained-in` rule (job 0b — needs the real tree from next-bar Task N3)

**Files:**
- Modify: `rules/rules.py` (new `rule_contained_in(screens, cfg, report)` after `rule_content_in_bounds`; one call in `run()`; `README.md` rule list)
- Modify: `rules/test_rules.py` (new tests; `ALL_RULES`; the bad-tour fixture; the call list)

**Interfaces:**
- Consumes: `rules.json` key `containedIn: [{"child": "<regex>", "container": "<regex>"}]`; stops' `elements` with `identifier` and `frame = (x, y, w, h) | None`.
- Produces: findings under rule name `contained-in`, `where = f"{screen['fixture']}/{screen['flow']}"`, messages: `"{container_id} has no {child regex} inside it"` and `"{child_id} ({x:.0f},{y:.0f} {w:.0f}×{h:.0f}) sticks out of {container_id} ({cx:.0f},{cy:.0f} {cw:.0f}×{ch:.0f})"`. `report.count("contained-in")` once per (stop, matched container).

- [ ] **Step 1: Write the failing tests** in `rules/test_rules.py`, synthetic trees in the file's `TREE` style, **the failing one pasted from the real `tabs/map-card` tree captured in next-bar Task N3** (trim to the card's subtree; keep real frames):
  - `test_contained_in_fails_when_child_missing` — container `map.card` present, no `map.card.name` → exactly one finding containing "has no".
  - `test_contained_in_fails_when_child_sticks_out` — child frame y+h > container y+h (the real capture) → one finding containing "sticks out".
  - `test_contained_in_passes_when_inside` — hand-corrected copy (child inside) → no findings.
  - `test_contained_in_child_without_frame_is_missing` — child present with no frame → "has no".
  - `test_contained_in_two_containers_one_holds_child` — `map.card` and `map.card.parked` both match, child inside the second → no findings, count 2.
  - `test_contained_in_noop_without_config` — `CONFIG` without `containedIn` → no findings, count 0.
  - Config used: `{**CONFIG, "containedIn": [{"child": r"^map\.card\.name$", "container": r"^map\.card(\.parked)?$"}]}`.
  - Add `"contained-in"` to `ALL_RULES` and extend the bad-tour fixture so it fails this rule (a `map.card` with no name, plus `containedIn` in the bad config).
  - Register the six tests in the call list.
- [ ] **Step 2: Run:** `python3 rules/test_rules.py` → FAIL (`AttributeError: module 'rules' has no attribute 'rule_contained_in'` or the first assertion).
- [ ] **Step 3: Implement `rule_contained_in(screens, cfg, report)`** in `rules/rules.py`: for each pair, for each stop, containers = elements whose identifier matches `container` and have a frame; if none, continue; children = elements matching `child` with a frame; pass if any child is inside any container (`cx-0.5 <= x and cy-0.5 <= y and x+w <= cx+cw+0.5 and y+h <= cy+ch+0.5`); else fail with the matching message (missing when `children` empty, sticks-out otherwise, naming the first child and first container). Call it in `run()` right after `rule_content_in_bounds`.
- [ ] **Step 4: Run:** `python3 rules/test_rules.py` → `rules self-check: ok`.
- [ ] **Step 5: README:** one bullet under the rules list: `contained-in`: pairs in `containedIn`; a container on screen must hold its child, fully.
- [ ] **Step 6: Commit** `feat(rules): [T1] contained-in — a named child must exist inside its container (NextBar map card lost its bar name)` with `Spec:` line and `Fixture: next-bar run <id>, stop tabs/map-card`.
- [ ] **Step 7: Review + push:** Codex review (base = the K2 push sha); fix 🔴s with fix plans; `git push origin HEAD:nextbar-sheet-safe-clear`; record the sha for next-bar Task N4.
