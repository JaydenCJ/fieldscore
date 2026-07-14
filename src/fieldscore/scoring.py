"""The scoring engine: per-field precision / recall / F1.

For every aligned record pair and every field path, one of four things is
true, and each feeds the counts differently:

* both sides have a value and the comparator accepts it  → **correct** (TP)
* both sides have a value and the comparator rejects it  → **wrong**
  (hurts precision *and* recall: the model produced something, and the gold
  value went unmatched)
* only gold has a value                                  → **missing** (FN)
* only the prediction has a value                        → **spurious** (FP)

Precision is ``correct / predicted`` and recall is ``correct / gold``, where
*predicted* and *gold* count extracted values (list elements count
individually). Micro averages pool the raw counts across fields; macro
averages the per-field F1 values, weighting rare fields equally with
common ones.

Scalar lists match as multisets by default (``ordered: true`` in the config
pins element order). Lists of objects — invoice line items, resume entries —
are aligned element-to-element by greedy best-overlap, then scored per leaf
field under the ``path[]`` prefix, so a single swapped line item cannot
cascade into every field of every later item being wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .comparators import Comparator
from .config import FieldConfig
from .flatten import LIST_MARKER, flatten, is_object_list
from .loader import AlignedPair


@dataclass
class FieldCounts:
    """Raw tallies for one field across all records."""

    gold: int = 0        # gold values that should have been extracted
    pred: int = 0        # values the model actually produced
    correct: int = 0     # pairs the comparator accepted

    @property
    def precision(self) -> float:
        return self.correct / self.pred if self.pred else 0.0

    @property
    def recall(self) -> float:
        return self.correct / self.gold if self.gold else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def add(self, other: "FieldCounts") -> None:
        self.gold += other.gold
        self.pred += other.pred
        self.correct += other.correct


@dataclass
class Mismatch:
    """One scoring failure, kept for ``fieldscore explain``."""

    record_id: str
    path: str
    kind: str            # "wrong" | "missing" | "spurious"
    gold: Any = None
    pred: Any = None
    type_name: str = "auto"


@dataclass
class ScoreReport:
    """Everything one scoring run produced."""

    per_field: Dict[str, FieldCounts] = field(default_factory=dict)
    mismatches: List[Mismatch] = field(default_factory=list)
    record_count: int = 0
    gold_records: int = 0
    pred_records: int = 0

    @property
    def micro(self) -> FieldCounts:
        total = FieldCounts()
        for counts in self.per_field.values():
            total.add(counts)
        return total

    @property
    def macro_f1(self) -> float:
        if not self.per_field:
            return 0.0
        return sum(c.f1 for c in self.per_field.values()) / len(self.per_field)

    @property
    def macro_precision(self) -> float:
        if not self.per_field:
            return 0.0
        return sum(c.precision for c in self.per_field.values()) / len(self.per_field)

    @property
    def macro_recall(self) -> float:
        if not self.per_field:
            return 0.0
        return sum(c.recall for c in self.per_field.values()) / len(self.per_field)


class Scorer:
    """Scores aligned record pairs against a :class:`FieldConfig`."""

    def __init__(self, config: Optional[FieldConfig] = None):
        self.config = config or FieldConfig()

    # -- public API ---------------------------------------------------------

    def score(self, pairs: List[AlignedPair]) -> ScoreReport:
        report = ScoreReport(record_count=len(pairs))
        for pair in pairs:
            self.score_pair(pair, report)
            if pair.gold is not None:
                report.gold_records += 1
            if pair.pred is not None:
                report.pred_records += 1
        return report

    def score_pair(self, pair: AlignedPair, report: ScoreReport) -> None:
        gold_flat = flatten(pair.gold) if pair.gold is not None else {}
        pred_flat = flatten(pair.pred) if pair.pred is not None else {}
        id_field = self.config.id_field
        if id_field is not None:
            gold_flat.pop(id_field, None)
            pred_flat.pop(id_field, None)
        self._score_maps(gold_flat, pred_flat, "", pair.record_id, report)

    # -- internals ----------------------------------------------------------

    def _counts(self, report: ScoreReport, path: str) -> FieldCounts:
        return report.per_field.setdefault(path, FieldCounts())

    def _score_maps(
        self,
        gold_flat: Dict[str, Any],
        pred_flat: Dict[str, Any],
        prefix: str,
        record_id: str,
        report: ScoreReport,
    ) -> None:
        paths = list(gold_flat)
        paths.extend(p for p in pred_flat if p not in gold_flat)
        for path in paths:
            full_path = f"{prefix}{path}"
            gval = gold_flat.get(path)
            pval = pred_flat.get(path)
            ghas, phas = path in gold_flat, path in pred_flat
            if is_object_list(gval) or is_object_list(pval):
                self._score_object_lists(
                    _as_list(gval, ghas), _as_list(pval, phas),
                    full_path, record_id, report,
                )
            elif isinstance(gval, list) or isinstance(pval, list):
                self._score_scalar_lists(
                    _as_list(gval, ghas), _as_list(pval, phas),
                    full_path, record_id, report,
                )
            else:
                self._score_scalar(gval, pval, ghas, phas,
                                   full_path, record_id, report)

    def _score_scalar(
        self,
        gval: Any,
        pval: Any,
        ghas: bool,
        phas: bool,
        path: str,
        record_id: str,
        report: ScoreReport,
    ) -> None:
        comparator = self.config.comparator_for(path)
        counts = self._counts(report, path)
        if ghas:
            counts.gold += 1
        if phas:
            counts.pred += 1
        if ghas and phas:
            if comparator.match(gval, pval):
                counts.correct += 1
            else:
                report.mismatches.append(Mismatch(
                    record_id, path, "wrong", gval, pval, comparator.type_name))
        elif ghas:
            report.mismatches.append(Mismatch(
                record_id, path, "missing", gold=gval,
                type_name=comparator.type_name))
        elif phas:
            report.mismatches.append(Mismatch(
                record_id, path, "spurious", pred=pval,
                type_name=comparator.type_name))

    def _score_scalar_lists(
        self,
        gold_items: List[Any],
        pred_items: List[Any],
        path: str,
        record_id: str,
        report: ScoreReport,
    ) -> None:
        """Match scalar list elements as a multiset (or by index if ordered)."""
        comparator = self.config.comparator_for(path)
        counts = self._counts(report, path)
        counts.gold += len(gold_items)
        counts.pred += len(pred_items)
        if self.config.is_ordered(path):
            for gval, pval in zip(gold_items, pred_items):
                if comparator.match(gval, pval):
                    counts.correct += 1
                else:
                    report.mismatches.append(Mismatch(
                        record_id, path, "wrong", gval, pval,
                        comparator.type_name))
            for gval in gold_items[len(pred_items):]:
                report.mismatches.append(Mismatch(
                    record_id, path, "missing", gold=gval,
                    type_name=comparator.type_name))
            for pval in pred_items[len(gold_items):]:
                report.mismatches.append(Mismatch(
                    record_id, path, "spurious", pred=pval,
                    type_name=comparator.type_name))
            return
        remaining = list(pred_items)
        unmatched_gold: List[Any] = []
        for gval in gold_items:
            hit = next(
                (pval for pval in remaining if comparator.match(gval, pval)), _NOTHING
            )
            if hit is not _NOTHING:
                counts.correct += 1
                remaining.remove(hit)
            else:
                unmatched_gold.append(gval)
        for gval in unmatched_gold:
            report.mismatches.append(Mismatch(
                record_id, path, "missing", gold=gval,
                type_name=comparator.type_name))
        for pval in remaining:
            report.mismatches.append(Mismatch(
                record_id, path, "spurious", pred=pval,
                type_name=comparator.type_name))

    def _score_object_lists(
        self,
        gold_items: List[Any],
        pred_items: List[Any],
        path: str,
        record_id: str,
        report: ScoreReport,
    ) -> None:
        """Align object-list elements by best overlap, then score leaves.

        Every leaf count is attributed to ``path[].leaf`` so line items keep
        per-column metrics regardless of how the lists were ordered.
        """
        gold_flats = [flatten(item) if isinstance(item, dict) else {"": item}
                      for item in gold_items]
        pred_flats = [flatten(item) if isinstance(item, dict) else {"": item}
                      for item in pred_items]
        prefix = f"{path}{LIST_MARKER}."

        pairs = self._align_elements(gold_flats, pred_flats, prefix)
        used_pred = {j for _, j in pairs}
        used_gold = {i for i, _ in pairs}
        for i, j in pairs:
            self._score_maps(gold_flats[i], pred_flats[j], prefix,
                             record_id, report)
        for i, gflat in enumerate(gold_flats):
            if i not in used_gold:
                self._score_maps(gflat, {}, prefix, record_id, report)
        for j, pflat in enumerate(pred_flats):
            if j not in used_pred:
                self._score_maps({}, pflat, prefix, record_id, report)

    def _align_elements(
        self,
        gold_flats: List[Dict[str, Any]],
        pred_flats: List[Dict[str, Any]],
        prefix: str,
    ) -> List[Tuple[int, int]]:
        """Greedy best-overlap assignment between gold and pred elements.

        Overlap = number of leaf fields the comparator accepts. Ties break
        toward the original list order, so already-aligned lists stay
        aligned. Pairs with zero overlap are left unpaired: a completely
        unrelated predicted element is spurious, not a row of wrong values.
        """
        scored: List[Tuple[int, int, int]] = []
        for i, gflat in enumerate(gold_flats):
            for j, pflat in enumerate(pred_flats):
                overlap = self._element_overlap(gflat, pflat, prefix)
                if overlap > 0:
                    scored.append((overlap, i, j))
        scored.sort(key=lambda t: (-t[0], t[1], t[2]))
        taken_gold: set = set()
        taken_pred: set = set()
        pairs: List[Tuple[int, int]] = []
        for _, i, j in scored:
            if i in taken_gold or j in taken_pred:
                continue
            taken_gold.add(i)
            taken_pred.add(j)
            pairs.append((i, j))
        pairs.sort()
        return pairs

    def _element_overlap(
        self,
        gflat: Dict[str, Any],
        pflat: Dict[str, Any],
        prefix: str,
    ) -> int:
        overlap = 0
        for leaf, gval in gflat.items():
            if leaf not in pflat:
                continue
            pval = pflat[leaf]
            if isinstance(gval, (list, dict)) or isinstance(pval, (list, dict)):
                continue  # nested structures are scored later, not counted here
            comparator = self.config.comparator_for(f"{prefix}{leaf}")
            if comparator.match(gval, pval):
                overlap += 1
        return overlap


class _Nothing:
    """Sentinel distinct from every real value (None is a legal miss)."""


_NOTHING = _Nothing()


def _as_list(value: Any, present: bool) -> List[Any]:
    """Coerce a field value into an element list for list scoring.

    A scalar facing a list on the other side becomes a one-element list —
    ``"net30"`` vs ``["net30"]`` should cost one shape lecture, not a miss.
    """
    if not present:
        return []
    if isinstance(value, list):
        return value
    return [value]


def score_pairs(
    pairs: List[AlignedPair], config: Optional[FieldConfig] = None
) -> ScoreReport:
    """One-call façade over :class:`Scorer` (the API most callers want)."""
    return Scorer(config).score(pairs)
