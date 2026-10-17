#!/usr/bin/env python3
"""Run the blind screenshot reader (Claude Code headless) over a tour directory and extract its verdict.

    python3 run.py --tour <dir> --profile <profile.json> --rules-report <report.json> --out <reader.json>

Fails closed: no parsable verdict means FAIL. Needs `claude` on PATH and CLAUDE_CODE_OAUTH_TOKEN.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build_prompt(tour, profile, rules_report):
    core = (HERE / "core.md").read_text(encoding="utf-8")
    p = json.loads(Path(profile).read_text(encoding="utf-8"))
    report = json.loads(Path(rules_report).read_text(encoding="utf-8")) if rules_report and Path(rules_report).exists() else {}
    shots = sorted(x.name for x in Path(tour).glob("*.png"))
    return "\n\n".join([
        core,
        "## Profile\n\nWho the user is: " + p.get("user", "") + "\n\nWhat they hate: " + p.get("hates", "") +
        ("\n\nContext for these screenshots: " + p["context"] if p.get("context") else ""),
        "## Rules report\n\n```json\n" + json.dumps({k: report.get(k) for k in ("verdict", "findings")}, indent=1) + "\n```",
        "## Screenshots to read, in this order (" + str(len(shots)) + " files in the current directory)\n\n" + "\n".join(shots),
    ])


FENCE = re.compile(r"```([A-Za-z0-9_-]*)[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL)


def extract_verdict(text):
    """The verdict is the FINAL fence in the output: it must be a ```json fence holding the contracted
    object, with nothing but whitespace after it. Anything else is no verdict (fail closed)."""
    fences = list(FENCE.finditer(text))
    if not fences:
        return None
    last = fences[-1]
    if text[last.end():].strip():
        return None                      # prose or another fence after the verdict
    if last.group(1) != "json":
        return None
    try:
        obj = json.loads(last.group(2))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or obj.get("verdict") not in ("PASS", "FAIL"):
        return None
    screens = obj.get("screens_read")
    if type(screens) is not int or screens < 0:   # bool is an int in Python; refuse it
        return None
    findings = obj.get("findings")
    if not isinstance(findings, list):
        return None
    for f in findings:
        if not isinstance(f, dict) or f.get("severity") not in ("BLOCKER", "HIGH", "MEDIUM", "LOW"):
            return None
        if not isinstance(f.get("screen"), str) or not isinstance(f.get("what"), str) or not f["what"].strip():
            return None
    return obj


def consistent(verdict, expected_screens):
    """Derive the verdict from the contract, never from the model's word alone."""
    problems = []
    if expected_screens < 1:
        problems.append("no screenshots to read")
    if verdict["screens_read"] != expected_screens:
        problems.append(f"reader read {verdict['screens_read']} of {expected_screens} screenshots")
    if any(f["severity"] in ("BLOCKER", "HIGH") for f in verdict["findings"]):
        problems.append("BLOCKER/HIGH findings present")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tour", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--rules-report")
    ap.add_argument("--out", default="reader.json")
    ap.add_argument("--model", default="")
    ap.add_argument("--claude", default="claude")
    args = ap.parse_args(argv)

    prompt = build_prompt(args.tour, args.profile, args.rules_report)
    cmd = [args.claude, "-p", prompt, "--allowedTools", "Read,Glob", "--no-session-persistence", "--output-format", "text"]
    if args.model:
        cmd += ["--model", args.model]
    returncode = None
    try:
        proc = subprocess.run(cmd, cwd=args.tour, capture_output=True, text=True, timeout=1500)
        text, err, returncode = proc.stdout, proc.stderr[-2000:], proc.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        text, err = "", str(e)

    expected = len(list(Path(args.tour).glob("*.png")))
    verdict = extract_verdict(text) if returncode == 0 else None
    if verdict is None:
        why = "reader produced no valid verdict" + (f" (exit {returncode})" if returncode not in (None, 0) else "") + ": " + (err or text[-500:])
        result = {"verdict": "FAIL", "screens_read": 0, "findings": [{"severity": "BLOCKER", "screen": "", "what": why}]}
    else:
        result = dict(verdict)
        for problem in consistent(verdict, expected):
            result["verdict"] = "FAIL"
            result["findings"].append({"severity": "BLOCKER", "screen": "", "what": problem})
    result["expected_screens"] = expected
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    Path(args.out).with_suffix(".transcript.txt").write_text(text, encoding="utf-8")
    print(f"reader: {result['verdict']} ({result.get('screens_read')}/{expected} screens)")
    for f in result.get("findings", []):
        print(f"  {f.get('severity')}: {f.get('screen')}: {f.get('what')}")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
