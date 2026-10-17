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
    r"^(?P<indent>\s*)→?(?P<type>[A-Za-z]+), 0x[0-9a-fA-F]+,(?: pid: \d+,)?"
    r"(?: \{\{(?P<x>-?[\d.]+), (?P<y>-?[\d.]+)\}, \{(?P<w>-?[\d.]+), (?P<h>-?[\d.]+)\}\})?(?P<rest>.*)$"
)
ATTR = re.compile(r", (identifier|label|value|placeholderValue): '")
FLAGS = ("Selected", "Disabled", "Focused")


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
        rest = m.group("rest") or ""
        attrs = {"identifier": "", "label": "", "value": "", "placeholderValue": ""}
        marks = list(ATTR.finditer(rest))
        for i, mark in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(rest)
            chunk = rest[mark.end():end]
            for flag in FLAGS:
                if chunk.endswith(", " + flag):
                    chunk = chunk[: -len(flag) - 2]
            attrs[mark.group(1)] = chunk[:-1] if chunk.endswith("'") else chunk
        frame = None
        if m.group("x") is not None:
            frame = tuple(float(m.group(k)) for k in ("x", "y", "w", "h"))
        elements.append({
            "type": m.group("type"),
            "depth": len(m.group("indent")),
            "frame": frame,
            "flags": [f for f in FLAGS if rest.rstrip().endswith(f)],
            **attrs,
        })
    return elements


def load_tour(tour_dir):
    tour = Path(tour_dir)
    index = json.loads((tour / "index.json").read_text(encoding="utf-8"))
    taps = json.loads((tour / "taps.json").read_text(encoding="utf-8")) if (tour / "taps.json").exists() else []
    stops = []
    for entry in index:
        text = (tour / entry["tree"]).read_text(encoding="utf-8", errors="replace")
        stops.append({**entry, "elements": parse_tree(text)})
    return stops, taps


def element_key(el):
    return el["identifier"] or f"{el['type']}|{el['label']}|{el['value']}"


def screen_union(stops):
    """One ordered, de-duplicated element list per fixture+flow (union of its scroll stops)."""
    screens = {}
    for stop in stops:
        key = (stop["fixture"], stop["flow"])
        screen = screens.setdefault(key, {"fixture": stop["fixture"], "flow": stop["flow"], "elements": [], "seen": set(), "stops": []})
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

def rule_count_matches_rows(screens, cfg, report):
    """A stated count ("0 of 16", "2 sets × 5") must equal the rows shown under it."""
    patterns = [re.compile(p) for p in cfg.get("rowCountPatterns", cfg.get("countPatterns", []))]
    row_re = re.compile(cfg["rowIdentifier"]) if cfg.get("rowIdentifier") else None
    if not patterns or not row_re:
        return
    for screen in screens:
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


def rule_same_count_everywhere(screens, cfg, report):
    """The same titled item must state the same total on every screen (per fixture)."""
    patterns = [re.compile(p) for p in cfg.get("countPatterns", []) if "(?P<title>" in p]
    if not patterns:
        return
    by_fixture = {}
    for screen in screens:
        for el in screen["elements"]:
            t = texts(el)
            for p in patterns:
                m = p.search(t)
                if m and m.group("title") and m.group("total"):
                    title = re.sub(r"\s+", " ", m.group("title")).strip().lower()
                    by_fixture.setdefault(screen["fixture"], {}).setdefault(title, []).append((screen["flow"], int(m.group("total")), t))
    for fixture, titles in by_fixture.items():
        for title, sightings in titles.items():
            totals = {s[1] for s in sightings}
            report.count("same-count-everywhere")
            if len(totals) > 1:
                report.fail("same-count-everywhere", fixture,
                            f'"{title}" shows different totals: ' + "; ".join(f'{s[0]}: "{s[2]}"' for s in sightings))


def rule_no_duplicate_titles(screens, cfg, report):
    """No two blocks on one screen share a title."""
    title_re = re.compile(cfg["titleIdentifier"]) if cfg.get("titleIdentifier") else None
    title_pattern = re.compile(cfg["titlePattern"]) if cfg.get("titlePattern") else None
    if not title_re and not title_pattern:
        return
    for screen in screens:
        seen = {}
        for el in screen["elements"]:
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
            if key in seen and seen[key] != el["identifier"]:
                report.fail("no-duplicate-titles", f"{screen['fixture']}/{screen['flow']}", f'two blocks titled "{title}"')
            seen.setdefault(key, el["identifier"])


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
    """No "week N" text where N is not the fixture's current week."""
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


def rule_rows_reachable(screens, cfg, report):
    """Every row must be fully visible above any pinned bottom bar at some scroll stop."""
    row_re = re.compile(cfg["rowIdentifier"]) if cfg.get("rowIdentifier") else None
    bars = cfg.get("pinnedBars", [])
    if not row_re or not bars:
        return
    for screen in screens:
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


def rule_forbidden_text(screens, cfg, report):
    """App-specific text that must never appear (placeholders, debug strings, "nil", "Optional(")."""
    patterns = [re.compile(p) for p in cfg.get("forbiddenText", [r"Optional\(", r"\bnil\b", r"\bNaN\b", r"\bundefined\b"])]
    for screen in screens:
        for el in screen["elements"]:
            t = texts(el)
            for p in patterns:
                report.count("forbidden-text")
                if p.search(t):
                    report.fail("forbidden-text", f"{screen['fixture']}/{screen['flow']}", f'"{t}" matches forbidden pattern {p.pattern}')


def run(tour_dir, cfg, fixtures):
    stops, taps = load_tour(tour_dir)
    screens = screen_union(stops)
    report = Report()
    rule_count_matches_rows(screens, cfg, report)
    rule_same_count_everywhere(screens, cfg, report)
    rule_no_duplicate_titles(screens, cfg, report)
    rule_durations_in_minutes(screens, cfg, report)
    rule_no_stale_week(screens, cfg, report, fixtures)
    rule_rows_reachable(screens, cfg, report)
    rule_controls_change_screen(taps, report)
    rule_instruction_not_live(screens, cfg, report)
    rule_forbidden_text(screens, cfg, report)
    return {
        "verdict": "PASS" if not report.findings else "FAIL",
        "screens": [f"{s['fixture']}/{s['flow']}" for s in screens],
        "stops": len(stops),
        "checked": report.checked,
        "findings": report.findings,
    }


def fixtures_from_manifest(tour_json):
    if not tour_json or not Path(tour_json).exists():
        return {}
    manifest = json.loads(Path(tour_json).read_text(encoding="utf-8"))
    return {f["name"]: f for f in manifest.get("fixtures", [])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tour", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--manifest", help="tour.json, for per-fixture facts such as the current week")
    ap.add_argument("--out", default="rules-report.json")
    args = ap.parse_args(argv)
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    result = run(args.tour, cfg, fixtures_from_manifest(args.manifest))
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"rules: {result['verdict']} — {result['stops']} stops, {len(result['screens'])} screens, checks {result['checked']}")
    for f in result["findings"]:
        print(f"  FAIL {f['rule']} @ {f['where']}: {f['message']}")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
