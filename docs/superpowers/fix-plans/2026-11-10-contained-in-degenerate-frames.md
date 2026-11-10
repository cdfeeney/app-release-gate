# Fix plan: contained-in passes on degenerate frames (Codex r1, 2026-11-10)

## The finding

🔴 Both reproduce through `rule_contained_in` on HEAD 55f7b0f (failing tests below, output recorded in the task-3 report).

1. A zero-size child counts as a child. `map.card.name` at `(28, 577, 130.3, 0)` sits inside `map.card`'s box, so
   `inside()` is true and the stop passes although the name has no visible height.
2. A container without a frame is a silent skip. `framed` drops elements whose `frame` is `None` before the
   container match, so a stop whose `map.card` has no frame gets no count and no finding: PASS with nothing checked.

Rule broken: a check must never pass because the element it checks is malformed or unmeasurable.

## Every caller, file and data path

- Caller: `run()` in `rules/rules.py` (only call site), after `rule_content_in_bounds`. Tests call it directly
  through `contained_in()` in `rules/test_rules.py` and through `run_tour()` (bad/clean tour).
- Frame source: `parse_tree()` builds `frame` from the `LINE` regex. `None` when the tree line has no
  `{{x, y}, {w, h}}`; the regex accepts `-?[\d.]+`, so `w`/`h` can be `0.0` or negative.
- Siblings: `rule_content_in_bounds` skips frameless elements and accepts zero or negative width (a zero-width
  element at a valid x passes). `rule_rows_reachable` skips frameless rows and requires `h > 0` to call a row
  reachable (so zero-height rows fail there, the right way), but any framed pinned bar, even zero-size, sets
  `bar_top`. `visible_controls` already drops controls with `w <= 0 or h <= 0`.
- Config: only apps whose rules JSON has `containedIn` reach this code (`rules.example.json` has none).

## What could break

- Apps without `containedIn`: none; the rule returns before touching screens (`test_contained_in_noop_without_config`).
- The six existing tests: messages for "has no" and "sticks out" stay byte-identical; the count stays one per
  matched container per stop (`test_contained_in_two_containers_one_holds_child` asserts 2).
- Bad tour: its `map.card` has a real frame and no name, so it still fails with "has no". Clean tour: name has a
  positive frame inside the card, still passes.
- New behaviour: a frameless or zero-size container now yields a finding where it used to yield nothing. Intended.

## Same rule, other inputs

Rule: an element counts toward a check only if it has a frame with positive width AND height; a matched
container that cannot be measured is a finding. Inputs and planned tests:

| Input | Expected | Test |
|---|---|---|
| child zero height | not a child: "has no" | `test_contained_in_zero_size_child_is_missing` |
| child zero width | not a child: "has no" | same test, second case |
| child negative size | not a child: "has no" | same test, third case |
| child frame None | not a child: "has no" | existing `test_contained_in_child_without_frame_is_missing` |
| container frame None | counted, "map.card has no measurable frame" | `test_contained_in_unmeasurable_container_is_a_finding` |
| container zero size / negative | counted, same message | same test, second and third cases |
| container off-screen (positive frame) | still measured: child inside passes, outside fails | `test_contained_in_offscreen_container_still_measured` |
| child id on two elements, the degenerate one inside, the real one outside | "sticks out" naming the real frame | `test_contained_in_degenerate_duplicate_child_ignored` |
| two containers, one unmeasurable, other holds child | one finding (the unmeasurable one), count 2 | `test_contained_in_unmeasurable_container_is_a_finding`, fourth case |

## Failing tests first

Add the five tests above to `rules/test_rules.py` and register them in the self-check call list. On HEAD the zero-size
child, unmeasurable container and degenerate-duplicate cases must fail; the off-screen case documents current
behaviour and passes before and after. Then fix: one `has_area(frame)` helper; children filtered by it; containers
matched on identifier alone, each counted, unmeasurable ones reported, only measurable ones used for containment.

## What's out of scope

- Off-screen containers are not a finding here; visibility is not what this rule checks.
- Same weakness elsewhere, report only: `rule_content_in_bounds` passes zero- or negative-width elements;
  `rule_rows_reachable` lets a zero-size pinned bar lower `bar_top` to its y; `rule_content_in_bounds` and
  `rule_rows_reachable` silently skip frameless matches.
