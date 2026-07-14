# Contributing to fieldscore

Thanks for your interest in contributing. Issues, discussions, and pull
requests are all welcome.

## Development setup

```bash
git clone https://github.com/JaydenCJ/fieldscore
cd fieldscore
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the checks

```bash
pytest                 # 92 unit + CLI tests (tests/)
bash scripts/smoke.sh  # end-to-end smoke: score, explain, infer, exit codes
```

Both must pass before a pull request is reviewed; `smoke.sh` must print
`SMOKE OK`. The whole suite runs fully offline in under a second and needs
no API keys.

## Ground rules

- **No new runtime dependencies.** The package is standard-library only;
  that is a feature. Test-only dependencies belong in the `dev` extra.
- **Every comparator change needs a failing-side test.** Fuzzy matching is
  only trustworthy if the values that must *not* match are pinned too —
  add at least one negative case for any parser or comparator change.
- **Scoring semantics changes need docs.** Anything that changes how a
  count is tallied must update `docs/scoring.md` in the same pull request,
  because users gate CI on these numbers.
- **Keep the three READMEs aligned.** `README.md`, `README.zh.md`, and
  `README.ja.md` share the same structure; update all three when you change
  one (English is the authoritative version).

## Reporting bugs

Please include `fieldscore --version` output, a minimal gold/pred record
pair (two JSONL lines are usually enough), the config you scored with, and
the output of `fieldscore explain` for the affected record.

## Security

Please do not report security issues in public. Use GitHub's private
vulnerability reporting on this repository instead.
