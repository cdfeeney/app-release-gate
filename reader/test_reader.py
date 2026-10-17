"""Self-check for the reader's fail-closed contract (no Claude call).

    python3 test_reader.py
"""
import run

GOOD = 'chatter\n```json\n{"verdict": "PASS", "screens_read": 3, "findings": []}\n```\n'


def test_extract():
    assert run.extract_verdict(GOOD)["verdict"] == "PASS"
    assert run.extract_verdict("no block at all") is None
    assert run.extract_verdict('```json\n{"verdict": "MAYBE", "screens_read": 3, "findings": []}\n```') is None
    assert run.extract_verdict('```json\n{"verdict": "PASS", "findings": []}\n```') is None           # screens_read missing
    assert run.extract_verdict('```json\n{"verdict": "PASS", "screens_read": 1, "findings": [{"severity": "BAD"}]}\n```') is None
    # only the LAST block counts: a PASS followed by a FAIL is a FAIL
    last = run.extract_verdict(GOOD + '```json\n{"verdict": "FAIL", "screens_read": 3, "findings": [{"severity": "HIGH", "screen": "x", "what": "y"}]}\n```')
    assert last["verdict"] == "FAIL"


def test_consistency():
    assert run.consistent({"verdict": "PASS", "screens_read": 3, "findings": []}, 3) == []
    assert run.consistent({"verdict": "PASS", "screens_read": 2, "findings": []}, 3)                 # under-read
    assert run.consistent({"verdict": "PASS", "screens_read": 3, "findings": [{"severity": "HIGH"}]}, 3)  # PASS with a HIGH
    assert run.consistent({"verdict": "PASS", "screens_read": 0, "findings": []}, 0)                 # nothing to read


if __name__ == "__main__":
    test_extract()
    test_consistency()
    print("reader self-check: ok")
