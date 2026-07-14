# fieldscore examples

A five-invoice extraction eval set showing every comparator type in one run.

| File | Role |
|---|---|
| `gold.jsonl` | Hand-labeled expected output, one invoice per line |
| `pred.jsonl` | What a model "extracted" — same facts, different surface forms, plus a few real mistakes |
| `fields.json` | The scoring config: types, tolerances, fuzzy thresholds, `id_field` |

The prediction file is deliberately messy in ways that exact-match scoring
punishes but a human grader would accept:

- `"2024-03-05"` predicted as `"March 5, 2024"` and `"12/03/2024"` (day-first)
- `"$1,234.50"` predicted as `"1234.50 USD"`, `"€2,000.00"` as `"EUR 2.000,00"`
- `"Jane A. Smith"` predicted as `"Smith, Jane"`, `"Sato Yuki"` as `"Yuki Sato"`
- `paid: true` predicted as `"yes"`
- line items returned in a different order

It also contains genuine errors that must stay errors: a total off by a
factor of ten (`¥50,000` → `¥5,000`), a hallucinated tag, a dropped contact
name, and `"Virginia Potts"` predicted as `"Pepper Potts"` (a nickname is
not the gold value).

Run from the repository root:

```bash
fieldscore score examples/gold.jsonl examples/pred.jsonl --config examples/fields.json
fieldscore explain examples/gold.jsonl examples/pred.jsonl --config examples/fields.json
fieldscore infer examples/gold.jsonl --id-field invoice_id
```
