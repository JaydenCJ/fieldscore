# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-13

### Added

- Per-field precision / recall / F1 scoring for JSON extraction output,
  with micro (count-pooled) and macro (field-averaged) summaries.
- Seven type-aware comparators: `date` (ISO, slash/compact/CJK numeric,
  month-name and ordinal forms, `dayfirst` disambiguation), `money`
  (currency symbols and ISO codes, US/European separators, accounting
  negatives, absolute tolerance, `require_currency`), `name` (order- and
  accent-insensitive person names, honorific/suffix stripping,
  `"Last, First"` reordering, initial matching, `subset_ok`), `number`
  (separators, percent signs, abs/rel tolerance), `bool`
  (`true`/`yes`/`1` spellings), `string` (exact / casefold / normalized /
  fuzzy-with-threshold modes), and `auto` (per-pair type detection, the
  default).
- Nested-record flattening to dot paths with honest absence semantics
  (`None`, `""`, `[]`, `{}` count as "not extracted", never as values).
- List scoring: scalar lists as multisets (or `ordered: true`), lists of
  objects aligned element-to-element by greedy best-overlap and scored per
  leaf column under `path[].leaf`.
- Record alignment by position or by `id_field` join, with skipped and
  invented documents scored as misses and spurious fields respectively.
- JSON field config with hard validation (typos in types or option keys
  fail loudly) and CLI overrides (`--id-field`, `--dayfirst`).
- `fieldscore` CLI: `score` (table / markdown / csv / json output,
  `--fail-under` CI gate on micro-F1), `explain` (per-record mismatch
  listing naming the judging comparator), `infer` (generate a starter
  config from gold values, with a strict money shape so SKUs stay strings).
- Runnable five-invoice example under `examples/` exercising every
  comparator, plus `docs/scoring.md` documenting the counting rules.
- 92 offline deterministic tests and `scripts/smoke.sh` (prints `SMOKE OK`).

### Notes

- The repository ships no CI workflow; verification is local —
  `pip install -e '.[dev]' && pytest && bash scripts/smoke.sh`.

[0.1.0]: https://github.com/JaydenCJ/fieldscore/releases/tag/v0.1.0
