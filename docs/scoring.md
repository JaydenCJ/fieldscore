# Scoring semantics

This document is the contract behind every number fieldscore prints. If a
change to the code would change anything below, the change must update this
file in the same pull request.

## The four outcomes

For each aligned record pair and each field path, exactly one of four things
happens:

| Outcome | Condition | Effect |
|---|---|---|
| **correct** | both sides have a value, the comparator accepts | +1 gold, +1 pred, +1 correct |
| **wrong** | both sides have a value, the comparator rejects | +1 gold, +1 pred |
| **missing** | only gold has a value | +1 gold |
| **spurious** | only the prediction has a value | +1 pred |

A field absent from *both* sides is a true negative and contributes nothing.
**Absence** means the key is missing or its value is `None`, `""`, `[]`, or
`{}` — an extractor that outputs `"total": null` is treated identically to
one that omits `total`.

## Metrics

Per field:

```
precision = correct / pred      (of what the model produced, how much was right)
recall    = correct / gold      (of what should have been extracted, how much was found)
f1        = harmonic mean of the two
```

A **wrong** value therefore hurts both precision and recall — the model
produced something (pred +1 without correct +1) *and* the gold value went
unmatched (gold +1 without correct +1). This matches how a human grader
counts: a wrong total is worse than a blank one only in the precision
column, never in recall.

Aggregates:

- **micro** — pool the raw `gold` / `pred` / `correct` counts across all
  fields, then compute the metrics. Frequent fields dominate. This is the
  number `--fail-under` gates on.
- **macro** — average the per-field precision / recall / F1. Every field
  weighs the same, so a rare-but-critical field cannot hide behind a common
  easy one.

Empty denominators yield `0.0`, never a crash: a field with no predictions
has precision 0, a field with no gold values has recall 0.

## Record alignment

- **By position** (default): gold line *i* pairs with prediction line *i*.
  Length mismatches pad with an absent side.
- **By `id_field`**: records join on the stringified value of that field.
  A gold record with no prediction scores every field as *missing*; a
  prediction with no gold record scores every field as *spurious*. Duplicate
  ids and records lacking the id are hard errors — a silent misjoin would
  corrupt every downstream number. The id field itself is never scored.

## Lists

**Scalar lists** (`"tags": ["net30", "hardware"]`) match as multisets:
each gold element consumes the first predicted element the comparator
accepts. Leftover gold elements are *missing*, leftover predicted elements
are *spurious*, so one hallucinated tag costs exactly one count. Set
`"ordered": true` on the field to require positional equality instead.

**Lists of objects** (`"line_items": [...]`) are aligned element-to-element
before scoring: every gold/pred element pair gets an overlap score (the
number of leaf fields the comparators accept), and pairs are picked greedily
from the highest overlap down, ties breaking toward original order. Paired
elements are then scored leaf by leaf under the `path[].leaf` field name, so
a reordered line-item list scores identically to a sorted one, and one wrong
quantity does not turn the whole row — let alone the rows after it — into
mismatches. Elements with zero overlap stay unpaired: a completely unrelated
predicted row is *spurious*, not a row of wrongs.

**Shape forgiveness**: a scalar facing a one-element list (`"net30"` vs
`["net30"]`) is coerced and compared; extraction evals should not fail on
JSON shape quibbles the comparator can see through.

## Comparator fallbacks

Typed comparators (`date`, `money`, `number`) parse both sides. If both
parse, the typed rule decides. If exactly one parses, the values are
**wrong** — gold being a date and the prediction being prose is a real
error. If neither parses, the comparator falls back to normalized string
equality, so a field mislabeled as `date` in the config degrades to sane
behavior instead of failing everything.

Money-specific: currency is compared only when both sides carry one
(`"$10"` vs `"10"` matches by amount) unless `require_currency` is set;
amounts compare within an absolute `tolerance` (default `0`, exact).
