#!/usr/bin/env python3
"""app-release-gate rules: deterministic checks over what the tour saw.

Reads a tour output directory (index.json, taps.json, *.tree.txt from Tour.swift) and a per-app
rules.json. Writes report.json and prints a summary. Exit 1 when any rule fails.

Rules never read app code. They read the accessibility trees the app rendered.

    python3 rules.py --tour <dir> --config <rules.json> --out <report.json>
"""
import argparse
import json
import re
import sys
from pathlib import Path

LINE = re.compile(
    r"^(?P<indent>\s*)→?(?P<type>[A-Za-z]+), 0x[0-9a-fA-F]+(?:, pid: \d+)?"
    r"(?:, \{\{(?P<x>-?[\d.]+), (?P<y>-?[\d.]+)\}, \{(?P<w>-?[\d.]+), (?P<h>-?[\d.]+)\}\})?(?P<rest>.*)$"
)
ATTR = re.compile(r", (identifier|label|value|placeholderValue): '")
FLAGS = ("Selected", "Disabled", "Focused", "Enabled")


def strip_flags(chunk):
    """Remove every trailing ', Selected'/', Disabled'... from an attribute chunk; return (chunk, flags)."""
    flags = []
    changed = True
    while changed:
        changed = False
        for flag in FLAGS:
            if chunk.endswith(", " + flag):
                chunk = chunk[: -len(flag) - 2]
                flags.append(flag)
                changed = True
    return chunk, flags


def parse_tree(text):
    """Elements in document order from XCUIApplication.debugDescription."""
    elements = []
    in_tree = False
    for raw in text.splitlines():
        if raw.startswith("Element subtree:"):
            in_tree = True
            continue
        if raw.startswith("Path to element:") or raw.startswith("Query chain:"):
            break
        if not in_tree:
            continue
        m = LINE.match(raw)
        if not m:
            continue
        rest = (m.group("rest") or "").rstrip()
        rest, flags = strip_flags(rest)
        attrs = {"identifier": "", "label": "", "value": "", "placeholderValue": ""}
        marks = list(ATTR.finditer(rest))
        for i, mark in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(rest)
            chunk = rest[mark.end():end]
            attrs[mark.group(1)] = chunk[:-1] if chunk.endswith("'") else chunk
        frame = None
        if m.group("x") is not None:
            frame = tuple(float(m.group(k)) for k in ("x", "y", "w", "h"))
        elements.append({
            "type": m.group("type"),
            "depth": len(m.group("indent")),
            "frame": frame,
            "flags": flags,
            **attrs,
        })
    return elements


class TourInvalid(Exception):
    """The tour output cannot be trusted; the gate must FAIL rather than pass on nothing."""


def load_tour(tour_dir):
    tour = Path(tour_dir)
    index_path = tour / "index.json"
    if not index_path.exists():
        raise TourInvalid("index.json missing")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not index:
        raise TourInvalid("the tour captured no screens")
    if not (tour / "taps.json").exists():
        raise TourInvalid("taps.json missing")   # Tour.swift always writes it, even with no taps
    taps = json.loads((tour / "taps.json").read_text(encoding="utf-8"))
    stops = []
    for entry in index:
        png = tour / entry["png"]
        tree_path = tour / entry["tree"]
        if not png.exists() or png.stat().st_size == 0:
            raise TourInvalid(f"{entry['png']} missing or empty")
        if not tree_path.exists():
            raise TourInvalid(f"{entry['tree']} missing")
        text = tree_path.read_text(encoding="utf-8", errors="replace")
        elements = parse_tree(text)
        if "Element subtree:" not in text or len(elements) < 2:
            raise TourInvalid(f"{entry['tree']} is not a parsable accessibility tree ({len(elements)} elements)")
        # gate-perf is the app's clock for the tour (taps.json `app`), not a screen text: the tree dump truncates long
        # values, and "write=89 s..." read as 89 seconds to durations-in-minutes (ConorHealth run 5).
        stops.append({**entry, "elements": [e for e in elements if e["identifier"] != "gate-perf"]})
    return stops, taps


def element_key(el):
    return el["identifier"] or f"{el['type']}|{el['label']}|{el['value']}"


def screen_union(stops):
    """One ordered, de-duplicated element list per fixture+flow+screen (union of its scroll stops)."""
    screens = {}
    for stop in stops:
        key = (stop["fixture"], stop["flow"], stop.get("screen", stop["name"]))
        screen = screens.setdefault(key, {"fixture": stop["fixture"], "flow": f"{stop['flow']}/{key[2]}", "flow_name": stop["flow"],
                                          "screen": key[2], "elements": [], "seen": set(), "stops": []})
        screen["stops"].append(stop)
        for el in stop["elements"]:
            k = element_key(el)
            if k in screen["seen"]:
                continue
            screen["seen"].add(k)
            screen["elements"].append(el)
    return list(screens.values())


class Report:
    def __init__(self):
        self.findings = []
        self.checked = {}

    def fail(self, rule, where, message):
        self.findings.append({"rule": rule, "where": where, "message": message})

    def count(self, rule, n=1):
        self.checked[rule] = self.checked.get(rule, 0) + n


def texts(el):
    return " ".join(t for t in (el["label"], el["value"], el["placeholderValue"]) if t)


# ---------------------------------------------------------------- rules

def rule_count_matches_rows(screens, cfg, report, scrolled=None):
    """A stated count ("0 of 16", "2 sets × 5") must equal the rows shown under it. Only a screen the tour
    scrolled to the bottom shows every row (lazy lists drop off-screen rows); single screenshots are skipped."""
    patterns = [re.compile(p) for p in cfg.get("rowCountPatterns", cfg.get("countPatterns", []))]
    row_re = re.compile(cfg["rowIdentifier"]) if cfg.get("rowIdentifier") else None
    if not patterns or not row_re:
        return
    for screen in screens:
        if scrolled is not None and (screen["flow_name"], screen["screen"]) not in scrolled:
            continue
        header = None
        rows = []

        def close():
            if header is None:
                return
            if not rows and cfg.get("skipHeadersWithoutRows", True):
                return  # a header of a block whose rows carry other identifiers (or a collapsed card)
            report.count("count-matches-rows")
            stated = header["total"]
            if stated != len(rows):
                report.fail("count-matches-rows", f"{screen['fixture']}/{screen['flow']}",
                            f'"{header["text"]}" states {stated} but {len(rows)} rows follow it: {[r["identifier"] for r in rows]}')

        for el in screen["elements"]:
            t = texts(el)
            found = None
            for p in patterns:
                m = p.search(t)
                if m and "total" in m.groupdict() and m.group("total"):
                    found = {"text": t, "total": int(m.group("total"))}
                    break
            if found:
                close()
                header, rows = found, []
            elif header is not None and el["identifier"] and row_re.search(el["identifier"]):
                rows.append(el)
        close()


def title_line_before(elements, i):
    """Title for a count line that has none of its own: the StaticText immediately before it, on the same
    row (frames overlap vertically) — the "Daily mobility (5 min)" / "5 min · 0 of 6" two-line header layout.
    None when there is no such line; the caller fails closed on that."""
    el = elements[i]
    prev = elements[i - 1] if i > 0 else None
    if not (prev and prev["type"] == "StaticText" and prev["label"] and prev["frame"] and el["frame"]):
        return None
    top, bottom = el["frame"][1], el["frame"][1] + el["frame"][3]
    prev_top, prev_bottom = prev["frame"][1], prev["frame"][1] + prev["frame"][3]
    if prev_top < bottom and top < prev_bottom:
        return prev["label"]
    return None


def rule_same_count_everywhere(screens, cfg, report):
    """The same titled item must state the same total on every screen (per fixture).
    A count pattern with a (?P<title>) group carries its title; one without takes the StaticText beside it,
    and a count line with no title line beside it is a finding (never silently skipped)."""
    patterns = [re.compile(p) for p in cfg.get("countPatterns", [])]
    if not patterns:
        return
    by_fixture = {}
    for screen in screens:
        seen = set()
        for stop in screen["stops"]:
            els = stop["elements"]
            for i, el in enumerate(els):
                t = texts(el)
                for p in patterns:
                    m = p.search(t)
                    if not m or "total" not in m.groupdict() or not m.group("total"):
                        continue
                    titled = "title" in m.groupdict()
                    title = m.group("title") if titled else title_line_before(els, i)
                    if not title:
                        if ("orphan", t) not in seen:
                            seen.add(("orphan", t))
                            report.fail("same-count-everywhere", f"{screen['fixture']}/{screen['flow']}",
                                        f'"{t}" is a count line with no title line beside it ({stop["png"]})')
                        break
                    key = re.sub(r"\s+", " ", title).strip().lower()
                    shown = t if titled else f"{title} / {t}"
                    if (key, shown) not in seen:
                        seen.add((key, shown))
                        by_fixture.setdefault(screen["fixture"], {}).setdefault(key, []).append((screen["flow"], int(m.group("total")), shown))
                    break
    for fixture, titles in by_fixture.items():
        for title, sightings in titles.items():
            totals = {s[1] for s in sightings}
            report.count("same-count-everywhere")
            if len(totals) > 1:
                report.fail("same-count-everywhere", fixture,
                            f'"{title}" shows different totals: ' + "; ".join(f'{s[0]}: "{s[2]}"' for s in sightings))


def rule_no_duplicate_titles(screens, cfg, report):
    """No two blocks on one screen share a title. Checked per scroll stop, where duplicates are literal."""
    title_re = re.compile(cfg["titleIdentifier"]) if cfg.get("titleIdentifier") else None
    title_pattern = re.compile(cfg["titlePattern"]) if cfg.get("titlePattern") else None
    if not title_re and not title_pattern:
        return
    for screen in screens:
        reported = set()
        for stop in screen["stops"]:
            seen = {}
            for el in stop["elements"]:
                if title_re and el["identifier"] and title_re.search(el["identifier"]):
                    title = el["label"]
                elif title_pattern and el["type"] == "StaticText":
                    m = title_pattern.search(el["label"])
                    title = m.group("title") if m else None
                else:
                    title = None
                if not title:
                    continue
                key = re.sub(r"\s+", " ", title).strip().lower()
                report.count("no-duplicate-titles")
                seen[key] = seen.get(key, 0) + 1
                if seen[key] == 2 and key not in reported:
                    reported.add(key)
                    report.fail("no-duplicate-titles", f"{screen['fixture']}/{screen['flow']}", f'two blocks titled "{title}" ({stop["png"]})')


def rule_durations_in_minutes(screens, cfg, report):
    """Any duration at or above the threshold must not be shown in seconds."""
    threshold = int(cfg.get("minutesThreshold", 60))
    allow = [re.compile(p) for p in cfg.get("durationAllow", [])]
    seconds = re.compile(r"(?<![\d.])(\d[\d,]*)\s?(?:s|sec|secs|seconds)\b")
    for screen in screens:
        for el in screen["elements"]:
            t = texts(el)
            for m in seconds.finditer(t):
                report.count("durations-in-minutes")
                value = int(m.group(1).replace(",", ""))
                if value >= threshold and not any(a.search(t) for a in allow):
                    report.fail("durations-in-minutes", f"{screen['fixture']}/{screen['flow']}", f'"{t}" shows {value} seconds; show minutes')


def rule_no_stale_week(screens, cfg, report, fixtures):
    """No "week N" text where N is not the fixture's current week. Progression prose such as
    "couch stretch at a bench from week 3" is allowed only through an explicit weekAllow pattern."""
    week_re = re.compile(cfg.get("weekPattern", r"\bweek (\d+)\b"), re.IGNORECASE)
    allow = [re.compile(p, re.IGNORECASE) for p in cfg.get("weekAllow", [])]
    for screen in screens:
        current = fixtures.get(screen["fixture"], {}).get("week")
        if current is None:
            continue
        for el in screen["elements"]:
            t = texts(el)
            for m in week_re.finditer(t):
                report.count("no-stale-week")
                if int(m.group(1)) != int(current) and not any(a.search(t) for a in allow):
                    report.fail("no-stale-week", f"{screen['fixture']}/{screen['flow']}", f'"{t}" mentions week {m.group(1)} during week {current}')


def rule_rows_reachable(screens, cfg, report, scrolled=None):
    """Every row must be fully visible above any pinned bottom bar at some scroll stop.
    Only screens the tour scrolled to the bottom (scrolled = {(flow, screen)}) can prove that; a single
    screenshot legitimately has rows below the fold. None = no manifest known, check every screen."""
    row_re = re.compile(cfg["rowIdentifier"]) if cfg.get("rowIdentifier") else None
    bars = cfg.get("pinnedBars", [])
    if not row_re or not bars:
        return
    for screen in screens:
        if scrolled is not None and (screen["flow_name"], screen["screen"]) not in scrolled:
            continue
        reachable = set()
        seen = {}
        for stop in screen["stops"]:
            height = float(stop.get("window", {}).get("height") or 0)
            bar_top = height
            for el in stop["elements"]:
                if el["identifier"] in bars and el["frame"]:
                    bar_top = min(bar_top, el["frame"][1])
            for el in stop["elements"]:
                if not (el["identifier"] and row_re.search(el["identifier"]) and el["frame"]):
                    continue
                seen[el["identifier"]] = el
                x, y, w, h = el["frame"]
                if h > 0 and y >= 0 and y + h <= bar_top:
                    reachable.add(el["identifier"])
        for ident in seen:
            report.count("rows-reachable")
            if ident not in reachable:
                report.fail("rows-reachable", f"{screen['fixture']}/{screen['flow']}", f"row {ident} is never fully visible above the pinned bar")


def rule_controls_change_screen(taps, report):
    """Every control the tour tapped must change something on screen."""
    for tap in taps:
        report.count("controls-change-screen")
        if tap.get("expected", True) and not tap.get("changed"):
            report.fail("controls-change-screen", tap.get("step", ""), f'tapping {tap.get("identifier")} changed nothing')


def rule_instruction_not_live(screens, cfg, report):
    """Text that is an instruction must not be a tappable item."""
    patterns = [re.compile(p, re.IGNORECASE) for p in cfg.get("instructionPatterns", [])]
    if not patterns:
        return
    for screen in screens:
        for el in screen["elements"]:
            if el["type"] not in ("Button", "Switch", "Cell"):
                continue
            t = texts(el)
            for p in patterns:
                report.count("instruction-not-live")
                if p.search(t):
                    report.fail("instruction-not-live", f"{screen['fixture']}/{screen['flow']}", f'"{t}" is an instruction but is a {el["type"]}')


def fixture_patterns(cfg, fixture, key, default=()):
    """Patterns for one rule: the global list plus the fixture's own ("fixtures": {"<name>": {"<key>": [...]}}),
    so a bug that only shows with certain data (Find rows on an exercise the fixture's history already weighs)
    is a rule on that fixture alone."""
    own = cfg.get("fixtures", {}).get(fixture, {}).get(key, [])
    return [re.compile(p) for p in list(cfg.get(key, list(default))) + list(own)]


def rule_forbidden_text(screens, cfg, report):
    """App-specific text that must never appear (placeholders, debug strings, "nil", "Optional(")."""
    default = (r"Optional\(", r"\bnil\b", r"\bNaN\b", r"\bundefined\b")
    for screen in screens:
        patterns = fixture_patterns(cfg, screen["fixture"], "forbiddenText", default)
        for el in screen["elements"]:
            t = texts(el)
            for p in patterns:
                report.count("forbidden-text")
                if p.search(t):
                    report.fail("forbidden-text", f"{screen['fixture']}/{screen['flow']}", f'"{t}" matches forbidden pattern {p.pattern}')


def rule_forbidden_identifiers(screens, cfg, report):
    """Controls that must never be on screen, by accessibility identifier: per-side rows, in-app hold timers,
    a weight-chip grid (owner 10-16/10-17). A per-fixture list catches controls that are wrong only with that
    fixture's data (Find rows on an exercise whose weight the history already knows)."""
    for screen in screens:
        patterns = fixture_patterns(cfg, screen["fixture"], "forbiddenIdentifiers")
        if not patterns:
            continue
        reported = set()
        for el in screen["elements"]:
            ident = el["identifier"]
            if not ident:
                continue
            for p in patterns:
                report.count("forbidden-identifiers")
                if p.search(ident) and (ident, p.pattern) not in reported:
                    reported.add((ident, p.pattern))
                    report.fail("forbidden-identifiers", f"{screen['fixture']}/{screen['flow']}",
                                f'{el["type"]} "{ident}" ({texts(el)[:60]}) matches forbidden identifier {p.pattern}')


def rule_taps_respond(taps, cfg, report):
    """Every tap must be answered within maxTapMillis (owner 10-17: "buttons take three or four seconds").
    Tour.swift records `idleMs`, the time the tap call itself took (XCUITest returns only when the app is idle again,
    so a main-thread stall is inside it), and `ms`, until the tree first differed (that includes one tree snapshot,
    about a second on a big screen, so it is only the fallback for older tours). A tap that was performed but carries
    no timing is a finding, never a silent skip: a tour copy older than these rules proves nothing about latency."""
    limit = int(cfg.get("maxTapMillis", 1500))
    for tap in taps:
        if tap.get("revealed") is False:
            continue   # never tapped; controls-change-screen reports it
        report.count("taps-respond")
        if "idleMs" in tap:
            # settleMs: the idle wait a probe tap met 0.8 s later, i.e. work the app deferred past the tap
            took, what = int(tap["idleMs"]), "to go idle after the tap"
            if int(tap.get("settleMs", 0)) > took:
                took, what = int(tap["settleMs"]), "to go idle 0.8 s after the tap (deferred work)"
        elif "ms" in tap:
            took, what = int(tap["ms"]), "to change the screen (older tour: includes one tree snapshot)"
        else:
            report.fail("taps-respond", tap.get("step", ""), f'tapping {tap.get("identifier")} recorded no timing (Tour.swift copy older than the rules)')
            continue
        if took > limit:
            report.fail("taps-respond", tap.get("step", ""), f'tapping {tap.get("identifier")} took {took} ms {what} (limit {limit} ms)')


def rule_app_timings(taps, cfg, report):
    """The app's own clocks: after every tap Tour.swift reads an element `gate-perf` ("tap=123 write=4 sync=1") into
    the tap's `app` dict. XCUITest's idle wait includes animations and ~0.5 s of harness overhead, so it cannot tell a
    100 ms tick from a 600 ms one; the app can (owner 10-18: the simulator numbers under-reported the phone).
    - every key in `maxAppMillis` must stay within its budget;
    - a tap whose identifier matches `appTimedIdentifiers` without `app` fails closed (the screen lost its clock);
    - `sync` must not rise into a tap marked `afterBackground`: an unlock between sets must never run a sync."""
    budgets = {k: int(v) for k, v in cfg.get("maxAppMillis", {}).items()}
    timed = [re.compile(p) for p in cfg.get("appTimedIdentifiers", [])]
    if not budgets and not timed:
        return
    last_sync, last_sample, fixture = None, None, None
    for tap in taps:
        if tap.get("revealed") is False:
            continue
        ident, step, app = tap.get("identifier", ""), tap.get("step", ""), tap.get("app") or {}
        if step.split("/")[0] != fixture:   # a new launch: the app's counters start again
            last_sync, last_sample, fixture = None, None, step.split("/")[0]
        report.count("app-timings")
        is_timed = any(p.search(ident) for p in timed)
        if is_timed:
            # every budgeted clock plus `n`, the app's count of completed measurements: a reading that did not advance
            # since the last timed tap is the previous tap's number, not this one's
            missing = [k for k in list(budgets) + ["n"] if k not in app]
            if missing:
                report.fail("app-timings", step, f'tapping {ident} recorded no app timings for {", ".join(missing)} (gate-perf missing or incomplete)')
            elif last_sample is not None and int(app["n"]) <= last_sample:
                report.fail("app-timings", step, f'tapping {ident} left the app\'s timing sample at n={app["n"]} (stale: the previous timed tap was n={last_sample})')
            if "n" in app:
                last_sample = int(app["n"])
        for key, limit in budgets.items():
            if key in app and int(app[key]) > limit:
                report.fail("app-timings", step, f'the app took {int(app[key])} ms ({key}) after tapping {ident} (limit {limit} ms)')
        away = tap.get("afterBackground")
        if away:
            if "sync" not in app or last_sync is None:
                report.fail("app-timings", step, f'{ident} follows {away.get("seconds")} s in the background but the sync count is not readable on both sides of it')
            elif int(app["sync"]) > last_sync:
                report.fail("app-timings", step, f'the app synced on returning from {away.get("seconds")} s in the background before {ident} (sync count {last_sync} -> {app["sync"]})')
        if "sync" in app:
            last_sync = int(app["sync"])


def run(tour_dir, cfg, fixtures, scrolled=None):
    try:
        stops, taps = load_tour(tour_dir)
    except TourInvalid as e:
        return {"verdict": "FAIL", "screens": [], "stops": 0, "checked": {},
                "findings": [{"rule": "tour-valid", "where": str(tour_dir), "message": str(e)}]}
    screens = screen_union(stops)
    report = Report()
    rule_count_matches_rows(screens, cfg, report, scrolled)
    rule_same_count_everywhere(screens, cfg, report)
    rule_no_duplicate_titles(screens, cfg, report)
    rule_durations_in_minutes(screens, cfg, report)
    rule_no_stale_week(screens, cfg, report, fixtures)
    rule_rows_reachable(screens, cfg, report, scrolled)
    rule_controls_change_screen(taps, report)
    rule_instruction_not_live(screens, cfg, report)
    rule_forbidden_text(screens, cfg, report)
    rule_forbidden_identifiers(screens, cfg, report)
    rule_taps_respond(taps, cfg, report)
    rule_app_timings(taps, cfg, report)
    return {
        "verdict": "PASS" if not report.findings else "FAIL",
        "screens": [f"{s['fixture']}/{s['flow']}" for s in screens],
        "stops": len(stops),
        "checked": report.checked,
        "findings": report.findings,
    }


def load_manifest(tour_json):
    if not tour_json or not Path(tour_json).exists():
        return None
    return json.loads(Path(tour_json).read_text(encoding="utf-8"))


def fixtures_from_manifest(manifest):
    return {f["name"]: f for f in (manifest or {}).get("fixtures", [])}


def scrolled_from_manifest(manifest):
    """(flow, screen) pairs the tour scrolled to the bottom; screen names follow Tour.swift (shot or step<i>)."""
    if manifest is None:
        return None
    return {(flow["name"], step["shot"] if step.get("shot") is not None else f"step{i}")
            for flow in manifest.get("flows", []) for i, step in enumerate(flow.get("steps", [])) if step.get("scrollToBottom")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tour", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--manifest", help="tour.json, for per-fixture facts such as the current week")
    ap.add_argument("--out", default="rules-report.json")
    args = ap.parse_args(argv)
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    manifest = load_manifest(args.manifest)
    result = run(args.tour, cfg, fixtures_from_manifest(manifest), scrolled_from_manifest(manifest))
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"rules: {result['verdict']} — {result['stops']} stops, {len(result['screens'])} screens, checks {result['checked']}")
    for f in result["findings"]:
        print(f"  FAIL {f['rule']} @ {f['where']}: {f['message']}")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
