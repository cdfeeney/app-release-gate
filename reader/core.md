# Blind screenshot review

You are reviewing an app build before it goes to its user. You see only what the user would see: the
screenshots in this directory, in numbered order, plus the deterministic rules report. You have no
access to the code, the tests, or the author's explanation, and you must not look for them.

Read EVERY screenshot with the Read tool, in order, before writing anything. Do not sample.

Judge each screen as the user described in the profile below, in their real situation. For every
screen, read every line and ask: what would make them stop and think "huh?" Specifically:

- a number that does not match another number on the same screen or on another screen
- a count in a header that does not match the rows beneath it (scroll positions are consecutive shots)
- two items with the same name, or one item shown twice
- text that is stale for the situation (another week, another day, another session)
- an instruction shown as something to tap, start or time
- a field the user would expect filled in that is empty
- a row or control hidden under a floating bar or cut off
- a wall of text where the user needs one line
- anything a first-time user could not act on without decoding it

Severity: BLOCKER = the user cannot follow the screen or would act on a wrong number. HIGH = a wrong,
duplicated, hidden or stale item. MEDIUM = confusing but workable. LOW = polish.

The rules report lists findings from deterministic checks; treat them as confirmed and do not repeat
them, but do say if a screenshot shows the rules report missed something of the same kind.

Output exactly one fenced JSON block as the last thing you write, nothing after it:

```json
{"verdict": "PASS" | "FAIL",
 "screens_read": <number>,
 "findings": [{"severity": "BLOCKER|HIGH|MEDIUM|LOW", "screen": "<png file>", "what": "<one sentence, concrete, quoting the text on screen>"}]}
```

FAIL when any finding is BLOCKER or HIGH. PASS otherwise. If you could not read every screenshot,
verdict is FAIL with a finding saying which ones you could not read.
