"""Self-check for rules.py: a fake tour with one of each bug must fail every rule; a clean one must pass.

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
      StaticText, 0x3, {{16.0, 60.0}, {300.0, 20.0}}, label: 'Daily mobility (5 min) · 0 of 4 done'
      Other, 0x4, {{0.0, 100.0}, {393.0, 30.0}}, identifier: 'coach-block-title-b1', label: 'Warm-up'
      StaticText, 0x5, {{16.0, 130.0}, {300.0, 20.0}}, label: '0 of 6 done'
      Button, 0x6, {{16.0, 160.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c0-s0', label: 'Leg swings', value: 'Not done'
      Button, 0x7, {{16.0, 210.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c1-s0-left', label: 'Side bridge', value: 'Not done'
      Button, 0x8, {{16.0, 260.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c1-s0-right', label: 'Side bridge', value: 'Not done'
      Button, 0x9, {{16.0, 310.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c2-s0', label: 'Couch stretch (from week 3)', value: 'Not done'
      Button, 0x10, {{16.0, 360.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b1-c3-s0', label: 'Easy cardio (skip it after Zone 2)'
      Other, 0x11, {{0.0, 420.0}, {393.0, 30.0}}, identifier: 'coach-block-title-b2', label: 'Warm-up'
      StaticText, 0x15, {{16.0, 440.0}, {300.0, 20.0}}, label: '0 of 1 done'
      StaticText, 0x12, {{16.0, 460.0}, {300.0, 20.0}}, label: 'Zone 2 · 1 set × 1,800 s'
      Button, 0x13, {{16.0, 800.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b2-c0-s0', label: 'Hidden row'
      StaticText, 0x14, {{16.0, 790.0}, {300.0, 20.0}}, identifier: 'coach-save-hint', label: 'Answer pain to save'
Path to element:
 →Application, 0x1, pid: 9
"""

TODAY = """Element subtree:
 →Application, 0x1, pid: 9, label: 'App'
    Window, 0x2, {{0.0, 0.0}, {393.0, 852.0}}
      StaticText, 0x3, {{16.0, 60.0}, {300.0, 20.0}}, label: 'Daily mobility (5 min) · 0 of 6 done'
Path to element:
"""

CONFIG = {
    "countPatterns": [r"^(?P<title>.+?) · (?P<done>\d+) of (?P<total>\d+) done$"],
    "rowCountPatterns": [r"^(?P<done>\d+) of (?P<total>\d+) done$"],
    "rowIdentifier": r"^coach-preparation-",
    "titleIdentifier": r"^coach-block-title-",
    "pinnedBars": ["coach-save-hint"],
    "instructionPatterns": [r"skip it"],
    "weekAllow": [],
}


def make_tour(tmp, session_tree, today_tree, taps):
    out = Path(tmp)
    (out / "001-wed-session-top-01.tree.txt").write_text(session_tree, encoding="utf-8")
    (out / "002-wed-today-top-01.tree.txt").write_text(today_tree, encoding="utf-8")
    (out / "index.json").write_text(json.dumps([
        {"n": 1, "fixture": "wed", "flow": "session", "name": "top", "png": "a.png", "tree": "001-wed-session-top-01.tree.txt", "window": {"width": 393, "height": 852}},
        {"n": 2, "fixture": "wed", "flow": "today", "name": "top", "png": "b.png", "tree": "002-wed-today-top-01.tree.txt", "window": {"width": 393, "height": 852}},
    ]), encoding="utf-8")
    (out / "taps.json").write_text(json.dumps(taps), encoding="utf-8")
    return out


def test_parser():
    els = rules.parse_tree(TREE)
    assert els[0]["type"] == "Application"
    row = next(e for e in els if e["identifier"] == "coach-preparation-b1-c1-s0-left")
    assert row["label"] == "Side bridge" and row["value"] == "Not done" and row["frame"] == (16.0, 210.0, 360.0, 44.0)
    assert next(e for e in els if e["identifier"] == "coach-block-title-b1")["label"] == "Warm-up"


def test_bad_tour_fails_every_rule():
    with tempfile.TemporaryDirectory() as tmp:
        out = make_tour(tmp, TREE, TODAY, [{"identifier": "coach-dead", "step": "s", "changed": False, "expected": True}])
        result = rules.run(out, CONFIG, {"wed": {"week": 2}})
    failed = {f["rule"] for f in result["findings"]}
    expected = {"count-matches-rows", "same-count-everywhere", "no-duplicate-titles", "durations-in-minutes",
                "no-stale-week", "rows-reachable", "controls-change-screen", "instruction-not-live"}
    missing = expected - failed
    assert not missing, f"rules that should have failed but passed: {missing}\n{json.dumps(result['findings'], indent=1)}"
    assert result["verdict"] == "FAIL"
    count = next(f for f in result["findings"] if f["rule"] == "count-matches-rows")
    assert "states 6 but 5 rows" in count["message"], count


def test_clean_tour_passes():
    clean = TREE.replace("0 of 6 done", "0 of 5 done").replace("1,800 s", "30 min").replace("(from week 3)", "").replace(
        "(skip it after Zone 2)", "").replace("coach-block-title-b2', label: 'Warm-up'", "coach-block-title-b2', label: 'Cool-down'").replace(
        "{{16.0, 800.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b2-c0-s0'", "{{16.0, 700.0}, {360.0, 44.0}}, identifier: 'coach-preparation-b2-c0-s0'")
    today = TODAY.replace("0 of 6 done", "0 of 4 done")
    with tempfile.TemporaryDirectory() as tmp:
        out = make_tour(tmp, clean, today, [{"identifier": "ok", "step": "s", "changed": True, "expected": True}])
        result = rules.run(out, CONFIG, {"wed": {"week": 2}})
    assert result["verdict"] == "PASS", json.dumps(result["findings"], indent=1)
    assert result["checked"]["count-matches-rows"] >= 1


if __name__ == "__main__":
    test_parser()
    test_bad_tour_fails_every_rule()
    test_clean_tour_passes()
    print("rules self-check: ok")
