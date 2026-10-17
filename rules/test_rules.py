"""Self-check for rules.py: a fake tour with one of each bug must fail every rule; a clean one must pass;
an empty or unparsable tour must FAIL rather than pass on nothing. The fake trees mirror the real
two-line header layout ("Daily mobility (5 min)" title line, "5 min · 0 of 6" count line on the same row).

    python3 test_rules.py
"""
import json
import tempfile
from pathlib import Path

import rules

TREE = """Attributes: Application, 0x1, pid: 9, label: 'App'
Element subtree:
 →Application, 0x1, pid: 9, label: 'App'
    Window, 0x2, {{0.0, 0.0}, {393.0, 852.0}}
      Other, 0x4, {{0.0, 100.0}, {393.0, 30.0}}, identifier: 'coach-block-title-b1', label: 'Warm-up'
      StaticText, 0x3, {{16.0, 130.0}, {180.0, 24.0}}, label: 'Daily mobility (5 min)'
      StaticText, 0x5, {{280.0, 136.0}, {80.0, 16.0}}, label: '5 min · 0 of 6'
      Button, 0x6, {{16.0, 160.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c0-s0', label: 'Leg swings, front-back', value: 'Not done', Selected, Disabled
      Button, 0x7, {{16.0, 210.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c1-s0-left', label: 'Side bridge', value: 'Not done'
      Button, 0x8, {{16.0, 260.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c1-s0-right', label: 'Side bridge', value: 'Not done'
      Button, 0x9, {{16.0, 310.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c2-s0', label: 'Couch stretch (at a bench from week 3)', value: 'Not done'
      Button, 0x10, {{16.0, 360.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c3-s0', label: 'Easy cardio (skip it after Zone 2)'
      StaticText, 0x17, {{16.0, 400.0}, {300.0, 20.0}}, label: 'Week 1: find your weight'
      Other, 0x11, {{0.0, 420.0}, {393.0, 30.0}}, identifier: 'coach-block-title-b2', label: 'Warm-up'
      StaticText, 0x15, {{16.0, 440.0}, {300.0, 20.0}}, label: '0 of 1 done'
      StaticText, 0x12, {{16.0, 460.0}, {300.0, 20.0}}, label: 'Zone 2 · 1 set × 1,800 s'
      StaticText, 0x16, {{16.0, 480.0}, {300.0, 20.0}}, label: 'Coach's note: nil'
      Button, 0x18, {{16.0, 500.0}, {120.0, 44.0}}, identifier: 'coach-timer-start-b1-c2-s0', label: 'Start hold'
      Button, 0x19, {{16.0, 550.0}, {80.0, 44.0}}, identifier: 'coach-select-weight-b3-e1-p0', label: 'Use 30 lb as work set 1'
      Button, 0x13, {{16.0, 800.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b2-c0-s0', label: 'Hidden row'
      StaticText, 0x14, {{16.0, 790.0}, {300.0, 20.0}}, identifier: 'coach-save-hint', label: 'Answer pain to save'
Path to element:
 →Application, 0x1, pid: 9
"""

TODAY = """Element subtree:
 →Application, 0x1, pid: 9, label: 'App'
    Window, 0x2, {{0.0, 0.0}, {393.0, 852.0}}
      StaticText, 0x3, {{16.0, 60.0}, {300.0, 20.0}}, label: 'Daily mobility (5 min) · 0 of 4 done'
Path to element:
"""

CONFIG = {
    "countPatterns": [r"^(?P<title>.+?) · (?P<done>\d+) of (?P<total>\d+) done$", r"^\d+ min · (?P<done>\d+) of (?P<total>\d+)$"],
    "rowCountPatterns": [r"^\d+ min · (?P<done>\d+) of (?P<total>\d+)$", r"^(?P<done>\d+) of (?P<total>\d+) done$"],
    "rowIdentifier": r"^coach-preparation-",
    "titleIdentifier": r"^coach-block-title-",
    "pinnedBars": ["coach-save-hint"],
    "instructionPatterns": [r"\(skip it"],
    "weekAllow": [r"\bfrom week \d+\b"],
    "forbiddenIdentifiers": [r"-(left|right)$", r"^coach-(timer|rest-timer|move-timer)-start-"],
    "fixtures": {"wed": {"forbiddenIdentifiers": [r"^coach-select-weight-b3-e1-"]}},
    "maxTapMillis": 1500,
}

ALL_RULES = {"count-matches-rows", "same-count-everywhere", "no-duplicate-titles", "durations-in-minutes",
             "no-stale-week", "rows-reachable", "controls-change-screen", "instruction-not-live", "forbidden-text",
             "forbidden-identifiers", "taps-respond"}
SCROLLED = {("session", "session"), ("today", "today")}
WEEK2 = {"wed": {"week": 2}}


def make_tour(tmp, session_tree, today_tree, taps, with_png=True):
    out = Path(tmp)
    (out / "001-wed-session-session-01.tree.txt").write_text(session_tree, encoding="utf-8")
    (out / "002-wed-today-today-01.tree.txt").write_text(today_tree, encoding="utf-8")
    if with_png:
        (out / "a.png").write_bytes(b"\x89PNG fake")
        (out / "b.png").write_bytes(b"\x89PNG fake")
    (out / "index.json").write_text(json.dumps([
        {"n": 1, "fixture": "wed", "flow": "session", "screen": "session", "name": "session-01", "png": "a.png", "tree": "001-wed-session-session-01.tree.txt", "window": {"width": 393, "height": 852}},
        {"n": 2, "fixture": "wed", "flow": "today", "screen": "today", "name": "today-01", "png": "b.png", "tree": "002-wed-today-today-01.tree.txt", "window": {"width": 393, "height": 852}},
    ]), encoding="utf-8")
    (out / "taps.json").write_text(json.dumps(taps), encoding="utf-8")
    return out


def run_tour(session_tree, today_tree, taps=(), config=CONFIG, fixtures=WEEK2, scrolled=SCROLLED):
    with tempfile.TemporaryDirectory() as tmp:
        out = make_tour(tmp, session_tree, today_tree, list(taps))
        return rules.run(out, config, fixtures, scrolled)


def findings(result, rule):
    return [f for f in result["findings"] if f["rule"] == rule]


def clean_trees():
    clean = (TREE.replace("5 min · 0 of 6", "5 min · 0 of 5").replace("1,800 s", "30 min · rest 45 s")
             .replace(" (skip it after Zone 2)", "").replace("Coach's note: nil", "Coach's note: easy day")
             .replace("Week 1: find your weight", "Find your weight the first time")
             .replace("coach-block-title-b2', label: 'Warm-up'", "coach-block-title-b2', label: 'Cool-down'")
             .replace("{{16.0, 800.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b2-c0-s0'",
                      "{{16.0, 700.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b2-c0-s0'")
             .replace("coach-timer-start-b1-c2-s0", "coach-video-b1-c2").replace("coach-select-weight-b3-e1-p0", "coach-ramp-load-b3-e1-p0")
             .replace("coach-preparation-b1-c1-s0-left", "coach-preparation-b1-c1-s0").replace("coach-preparation-b1-c1-s0-right", "coach-preparation-b1-c4-s0"))
    return clean, TODAY.replace("0 of 4 done", "0 of 5 done")


def test_parser():
    els = rules.parse_tree(TREE)
    app = els[0]
    assert app["type"] == "Application" and app["label"] == "App", app
    row = next(e for e in els if e["identifier"] == "coach-preparation-b1-c0-s0")
    assert row["label"] == "Leg swings, front-back", row       # comma inside a label
    assert row["value"] == "Not done" and row["frame"] == (16.0, 160.0, 360.0, 44.0), row
    assert sorted(row["flags"]) == ["Disabled", "Selected"], row  # every trailing flag stripped
    note = next(e for e in els if e["label"].startswith("Coach"))
    assert note["label"] == "Coach's note: nil", note              # apostrophe inside a label
    assert next(e for e in els if e["identifier"] == "coach-block-title-b1")["label"] == "Warm-up"


def test_bad_tour_fails_every_rule():
    result = run_tour(TREE, TODAY, [{"identifier": "coach-dead", "step": "s", "changed": False, "expected": True, "ms": 200},
                                    {"identifier": "coach-slow", "step": "t", "changed": True, "expected": True, "ms": 3400}])
    failed = {f["rule"] for f in result["findings"]}
    missing = ALL_RULES - failed
    assert not missing, f"rules that should have failed but passed: {missing}\n{json.dumps(result['findings'], indent=1)}"
    assert result["verdict"] == "FAIL"
    count = findings(result, "count-matches-rows")[0]
    assert "states 6 but 5 rows" in count["message"], count
    same = findings(result, "same-count-everywhere")
    assert len(same) == 1, same
    assert "daily mobility (5 min)" in same[0]["message"] and "0 of 4 done" in same[0]["message"] and "5 min · 0 of 6" in same[0]["message"], same
    dup = findings(result, "no-duplicate-titles")[0]
    assert "Warm-up" in dup["message"], dup
    stale = findings(result, "no-stale-week")
    assert len(stale) == 1 and "week 1" in stale[0]["message"], stale   # "from week 3" is allowed by weekAllow only
    forbidden = sorted(f["message"].split('"')[1] for f in findings(result, "forbidden-identifiers"))
    assert forbidden == ["coach-preparation-b1-c1-s0-left", "coach-preparation-b1-c1-s0-right",
                         "coach-select-weight-b3-e1-p0", "coach-timer-start-b1-c2-s0"], forbidden
    slow = findings(result, "taps-respond")
    assert len(slow) == 1 and "coach-slow" in slow[0]["message"] and "3400 ms" in slow[0]["message"], slow


def test_clean_tour_passes():
    clean, today = clean_trees()
    result = run_tour(clean, today, [{"identifier": "ok", "step": "s", "changed": True, "expected": True, "ms": 420}])
    assert result["verdict"] == "PASS", json.dumps(result["findings"], indent=1)
    for rule in ("count-matches-rows", "same-count-everywhere", "no-duplicate-titles", "durations-in-minutes",
                 "no-stale-week", "rows-reachable", "controls-change-screen", "forbidden-identifiers", "taps-respond"):
        assert result["checked"].get(rule, 0) >= 1, (rule, result["checked"])


def test_fixture_rules_apply_to_that_fixture_only():
    # the chip grid is forbidden on "wed" only (config above); the same tree under another fixture passes that pattern
    other = run_tour(TREE, TODAY, config={**CONFIG, "fixtures": {"thu": CONFIG["fixtures"]["wed"]}})
    assert not any("coach-select-weight" in f["message"] for f in findings(other, "forbidden-identifiers")), other["findings"]
    assert any("coach-select-weight" in f["message"] for f in findings(run_tour(TREE, TODAY), "forbidden-identifiers"))
    text = run_tour(TREE, TODAY, config={**CONFIG, "fixtures": {"wed": {"forbiddenText": [r"Hidden row"]}}})
    assert any("Hidden row" in f["message"] for f in findings(text, "forbidden-text")), text["findings"]


def test_taps_without_timing_fail_closed():
    clean, today = clean_trees()
    result = run_tour(clean, today, [{"identifier": "old", "step": "s", "changed": True, "expected": True}])   # a tour from before `ms`
    assert any("no timing" in f["message"] for f in findings(result, "taps-respond")), result["findings"]
    skipped = run_tour(clean, today, [{"identifier": "gone", "step": "s", "changed": False, "expected": True, "revealed": False}])
    assert not findings(skipped, "taps-respond") and findings(skipped, "controls-change-screen")   # never tapped: not a latency question
    limit = run_tour(clean, today, [{"identifier": "ok", "step": "s", "changed": True, "expected": True, "ms": 1500}])
    assert not findings(limit, "taps-respond"), "the limit itself passes"
    over = run_tour(clean, today, [{"identifier": "ok", "step": "s", "changed": True, "expected": True, "ms": 1501}], config={**CONFIG, "maxTapMillis": 1500})
    assert findings(over, "taps-respond")
    # idleMs (the app's own response) is judged when present; a slow tree snapshot in ms is not the app's fault
    idle = run_tour(clean, today, [{"identifier": "ok", "step": "s", "changed": True, "expected": True, "ms": 2600, "idleMs": 400}])
    assert not findings(idle, "taps-respond"), idle["findings"]
    stall = run_tour(clean, today, [{"identifier": "ok", "step": "s", "changed": True, "expected": True, "ms": 2600, "idleMs": 2200}])
    assert any("2200 ms to go idle" in f["message"] for f in findings(stall, "taps-respond")), stall["findings"]


def test_week_mentions_are_strict_unless_allowed():
    clean, today = clean_trees()
    strict = run_tour(clean, today, config={**CONFIG, "weekAllow": []})
    assert any("week 3" in f["message"] for f in findings(strict, "no-stale-week")), strict["findings"]   # without the allow, "from week 3" fails
    header = run_tour(clean.replace("Daily mobility (5 min)'", "Daily mobility (5 min) · Week 3'"), today)
    assert any("week 3" in f["message"] for f in findings(header, "no-stale-week")), header["findings"]  # a wrong-week header never passes


def test_count_line_without_a_title_line_fails():
    # the title line sits on another row: the count line is an orphan and must be a finding, not skipped
    orphan = TREE.replace("StaticText, 0x3, {{16.0, 130.0}, {180.0, 24.0}}", "StaticText, 0x3, {{16.0, 20.0}, {180.0, 24.0}}")
    result = run_tour(orphan, TODAY)
    msgs = [f["message"] for f in findings(result, "same-count-everywhere")]
    assert any("no title line beside it" in m and "5 min · 0 of 6" in m for m in msgs), msgs
    assert not any("different totals" in m for m in msgs), msgs            # the pair is not silently merged either


def test_rows_reachable_only_where_the_tour_scrolled():
    everywhere = run_tour(TREE, TODAY, fixtures={}, scrolled=None)      # no manifest: check every screen
    single_shots = run_tour(TREE, TODAY, fixtures={}, scrolled=set())   # nothing scrolled: a row below the fold is fine
    assert findings(everywhere, "rows-reachable") and findings(everywhere, "count-matches-rows")
    assert not findings(single_shots, "rows-reachable") and not findings(single_shots, "count-matches-rows")  # a single shot cannot show every row either
    manifest = {"flows": [{"name": "today", "steps": [{"waitFor": "x"}, {"scrollToBottom": True, "shot": "today"}]},
                          {"name": "session", "steps": [{"tap": "y"}, {"scrollToBottom": True}, {"shot": "after"}]},
                          {"name": "plan", "steps": [{"scrollToBottom": True, "shot": ""}]}]}
    assert rules.scrolled_from_manifest(manifest) == {("today", "today"), ("session", "step1"), ("plan", "")}  # same names as Tour.swift
    assert rules.scrolled_from_manifest(None) is None


def test_empty_or_broken_tour_fails():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "index.json").write_text("[]", encoding="utf-8")
        assert rules.run(tmp, CONFIG, {})["verdict"] == "FAIL"
    with tempfile.TemporaryDirectory() as tmp:
        assert rules.run(tmp, CONFIG, {})["verdict"] == "FAIL"           # no index at all
    with tempfile.TemporaryDirectory() as tmp:
        out = make_tour(tmp, "garbage that is not a tree", TODAY, [], with_png=True)
        assert rules.run(out, CONFIG, {})["verdict"] == "FAIL"           # unparsable tree
    with tempfile.TemporaryDirectory() as tmp:
        out = make_tour(tmp, TREE, TODAY, [], with_png=False)
        assert rules.run(out, CONFIG, {})["verdict"] == "FAIL"           # screenshots missing


if __name__ == "__main__":
    test_parser()
    test_bad_tour_fails_every_rule()
    test_clean_tour_passes()
    test_week_mentions_are_strict_unless_allowed()
    test_count_line_without_a_title_line_fails()
    test_rows_reachable_only_where_the_tour_scrolled()
    test_fixture_rules_apply_to_that_fixture_only()
    test_taps_without_timing_fail_closed()
    test_empty_or_broken_tour_fails()
    print("rules self-check: ok")
