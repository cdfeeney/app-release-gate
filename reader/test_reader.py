"""Self-check for the reader's fail-closed contract (no Claude call).

    python3 test_reader.py
"""
import run

GOOD = 'chatter\n```json\n{"verdict": "PASS", "screens_read": 3, "findings": []}\n```\n'


def test_extract():
    assert run.extract_verdict(GOOD)["verdict"] == "PASS"
    assert run.extract_verdict(GOOD + "\n   \n")["verdict"] == "PASS"                                   # trailing whitespace is fine
    assert run.extract_verdict("no block at all") is None
    assert run.extract_verdict('```json\n{"verdict": "MAYBE", "screens_read": 3, "findings": []}\n```') is None
    assert run.extract_verdict('```json\n{"verdict": "PASS", "findings": []}\n```') is None           # screens_read missing
    assert run.extract_verdict('```json\n{"verdict": "PASS", "screens_read": true, "findings": []}\n```') is None   # bool is not a count
    assert run.extract_verdict('```json\n{"verdict": "PASS", "screens_read": -1, "findings": []}\n```') is None
    assert run.extract_verdict('```json\n{"verdict": "PASS", "screens_read": 1, "findings": [{"severity": "BAD"}]}\n```') is None
    assert run.extract_verdict('```json\n{"verdict": "PASS", "screens_read": 1, "findings": [{"severity": "LOW"}]}\n```') is None  # screen/what missing
    # the FINAL fence decides: a PASS followed by a FAIL is a FAIL
    last = run.extract_verdict(GOOD + '```json\n{"verdict": "FAIL", "screens_read": 3, "findings": [{"severity": "HIGH", "screen": "x", "what": "y"}]}\n```')
    assert last["verdict"] == "FAIL"
    # anything after the verdict fence voids it: prose, a malformed json fence, a fence in another language
    assert run.extract_verdict(GOOD + "\nand one more thought") is None
    assert run.extract_verdict(GOOD + "```json\n{not json\n```") is None
    assert run.extract_verdict(GOOD + "```text\nnot allowed\n```") is None
    assert run.extract_verdict('```text\n{"verdict": "PASS", "screens_read": 3, "findings": []}\n```') is None  # wrong fence language


def test_consistency():
    assert run.consistent({"verdict": "PASS", "screens_read": 3, "findings": []}, 3) == []
    assert run.consistent({"verdict": "PASS", "screens_read": 2, "findings": []}, 3)                 # under-read
    assert run.consistent({"verdict": "PASS", "screens_read": 3, "findings": [{"severity": "HIGH"}]}, 3)  # PASS with a HIGH
    assert run.consistent({"verdict": "PASS", "screens_read": 0, "findings": []}, 0)                 # nothing to read


if __name__ == "__main__":
    test_extract()
    test_consistency()
    print("reader self-check: ok")
