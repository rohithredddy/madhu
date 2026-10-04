"""Scoring the answers: did the method point at the real cause?

These are the measurements the paper reports. They are kept apart from the
engines on purpose, because they are the only place ground truth is allowed to
appear: an engine never sees it (hard rule 4 in ``PROJECT_RULES.md``), and the scoring
never influences an engine. Keeping the two in separate modules makes that easy
to check rather than something to be careful about.

Three families:

* **Grounding** - ``ac_at_k``, ``avg_at_5``, ``exp_ac_at_k``. Was the true cause
  in the top k? At service level that is AC@k, as the benchmarks report it; at
  indicator level it is ExpAC@k, which is this project's addition and the harder
  question, because it asks *which metric* rather than merely which service.
* **Cause versus symptom** - ``symptom_error`` and ``symptom_rate``. When a method
  is wrong, is it wrong in the specific way this project is about: blaming a
  service that merely calls the broken one?
* **Explanation quality** - ``deletion_faithfulness``, ``topk_jaccard``,
  ``kendall_tau`` and ``compactness``. Is the explanation actually about the
  anomaly, is it stable, and is it short enough to read?

Definitions: ``docs/01_PROJECT_OVERVIEW.md`` glossary and
``docs/08_EXPERIMENTS_SPEC.md`` section 4.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pare.columns import ColumnInfo
from pare.graph import CallGraph
from pare.scores import robust_baseline, robust_z

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Rank:
    """Where the ground truth landed, including how many things tied with it.

    Ties are not a detail. Several methods saturate - ``ECDF``'s tail score cannot
    exceed ``log(n+1)``, so every column beyond the normal range scores exactly
    that - and then a dozen columns can share first place. Deciding those by
    alphabetical order would make the reported accuracy an accident of naming.

    So a tie is scored as what it is: the chance of being in the top k if the tied
    group were shuffled. With ``best`` the first rank the group occupies and
    ``tied`` its size, the group fills ranks ``best .. best + tied - 1``, and the
    ground truth is equally likely to be at any of them.
    """

    best: int
    """Best (lowest) rank the tied group occupies, 1-based."""

    tied: int = 1
    """How many items share that score. 1 means no tie."""

    def __post_init__(self) -> None:
        if self.best < 1:
            raise ValueError(f"a rank is 1-based, got {self.best}")
        if self.tied < 1:
            raise ValueError(f"a tie group holds at least one item, got {self.tied}")

    def hit_fraction(self, k: int) -> float:
        """The expected hit at top k: 1, 0, or a fraction when the cut falls
        inside a tie group.

        With no ties this is exactly the textbook definition, so nothing changes
        for a method whose scores are all distinct.
        """
        if k < 1:
            return 0.0
        inside = min(max(k - self.best + 1, 0), self.tied)
        return inside / self.tied


def rank_of(scores: Mapping[str, float], target: str) -> Rank | None:
    """Where ``target`` ranks among ``scores``, highest score first.

    Returns None when the target is absent - a service whose columns were all
    dropped in cleaning, say. ``docs/06`` section 5 records that as an empty rank
    rather than as a miss, because the method was never given the chance.
    """
    if target not in scores:
        return None

    target_score = scores[target]
    above = sum(1 for value in scores.values() if value > target_score)
    tied = sum(1 for value in scores.values() if value == target_score)
    return Rank(best=above + 1, tied=tied)


def rank_in_order(
    ordered: Sequence[str], scores: Mapping[str, float], target: str
) -> Rank | None:
    """Where ``target`` sits in the order an engine actually returned.

    Use this rather than :func:`rank_of` whenever the engine's ordering is its
    answer, which is the normal case. The two differ for `PARE`, because the
    graph traversal in ``docs/05`` step 4 deliberately promotes the service the
    walk ends at to rank 1 even when another service scores higher - that is the
    whole point of the step, following the graph down past a loud caller to the
    service the trouble started in. Re-deriving the rank from scores would throw
    that away and mark the engine wrong for being right.

    Ties are still honoured, but only where the engine genuinely could not
    separate two services: a run of **neighbours in its own ordering** that share
    an identical score. A tie that the engine's ordering has already broken on
    other grounds is not a tie.
    """
    if target not in ordered:
        return None

    position = list(ordered).index(target)
    target_score = scores.get(target)

    first, last = position, position
    if target_score is not None:
        while first > 0 and scores.get(ordered[first - 1]) == target_score:
            first -= 1
        while last + 1 < len(ordered) and scores.get(ordered[last + 1]) == target_score:
            last += 1

    return Rank(best=first + 1, tied=last - first + 1)


# --- grounding --------------------------------------------------------------


def ac_at_k(ranks: Iterable[Rank | int | None], k: int) -> float:
    """AC@k: how often the true cause was in the top k.

    Cases where the truth was never ranked at all count as misses, which is the
    honest reading - the method did not name it.
    """
    values = [_as_rank(rank) for rank in ranks]
    if not values:
        return 0.0
    return float(
        np.mean([0.0 if rank is None else rank.hit_fraction(k) for rank in values])
    )


def avg_at_5(ranks: Iterable[Rank | int | None]) -> float:
    """Avg@5: the mean of AC@1 through AC@5.

    One number that rewards being close rather than only being exactly right,
    which is how the RCAEval benchmark summarises a method.
    """
    values = list(ranks)
    return float(np.mean([ac_at_k(values, k) for k in range(1, 6)]))


def exp_ac_at_k(ranks: Iterable[Rank | int | None], k: int) -> float:
    """ExpAC@k: AC@k asked of indicators rather than services.

    The same arithmetic as :func:`ac_at_k` - it is a separate name because it is a
    different claim. Getting the service right narrows an incident to one team;
    getting the indicator right tells them which metric to look at, and the gap
    between the two is one of the paper's findings.
    """
    return ac_at_k(ranks, k)


# --- cause versus symptom ---------------------------------------------------


def symptom_error(
    top1: str | None, gt_service: str, graph: CallGraph | None
) -> bool | None:
    """Was this wrong answer wrong in the way this project is about?

    True when the top-ranked service is not the culprit **and** it calls the
    culprit, directly or through others. Those are the services that look broken
    because something they depend on is broken.

    Returns None when there is no graph to judge by, which ``docs/06`` section 5
    records as empty rather than as False - we cannot tell, and saying False
    would understate the problem.
    """
    if graph is None or graph.is_empty:
        return None
    if top1 is None:
        return None
    if top1 == gt_service:
        return False
    return top1 in graph.ancestors(gt_service)


def symptom_rate(errors: Iterable[bool | None]) -> float | None:
    """Of the wrong answers, the share that blamed a caller of the real cause.

    The denominator is wrong answers only, not all cases. A method that is right
    every time has no symptom rate at all, and reporting 0 for it would suggest it
    had been tested against the problem and passed, which it has not. That is why
    this returns None rather than 0 when nothing was wrong.
    """
    judged = [error for error in errors if error is not None]
    wrong = [error for error in judged if error is not False]
    if not wrong:
        return None
    return float(np.mean([1.0 if error else 0.0 for error in wrong]))


# --- explanation quality ----------------------------------------------------


@dataclass(frozen=True)
class DeletionCurve:
    """The result of the deletion test."""

    scores: tuple[float, ...]
    """System anomaly score after removing the top 0, 1, ... k columns."""

    normalised: tuple[float, ...]
    """The same, divided by the score before anything was removed."""

    auc: float
    """Mean of ``normalised``. Lower means a more faithful explanation."""


def system_anomaly_score(
    normal: npt.ArrayLike, abnormal: npt.ArrayLike
) -> float:
    """How abnormal the system looks as a whole.

    The mean, over the window, of the largest robust z across columns - "at each
    moment, how bad is the worst thing happening". Defined in
    ``docs/08`` section 4 and used by the deletion test.
    """
    baseline = robust_baseline(normal)
    z = np.abs(robust_z(abnormal, baseline))
    z = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
    if z.size == 0:
        return 0.0
    return float(np.mean(np.max(z, axis=1)))


def deletion_faithfulness(
    normal: npt.ArrayLike,
    abnormal: npt.ArrayLike,
    columns: Sequence[ColumnInfo],
    ranking: Sequence[str],
    max_k: int = 10,
) -> DeletionCurve:
    """Does removing what a method blamed actually remove the anomaly?

    For k = 0 to ``max_k``, replace the method's top k columns with their normal
    medians and recompute the system anomaly score. A faithful explanation makes
    the anomaly vanish quickly, so its curve falls fast and its area is small.

    This catches a specific kind of wrong answer: an explanation can name columns
    that merely moved alongside the anomaly without being it. Those columns are
    plausible to a reader and useless to an engineer, and only a test like this
    tells them apart. Compare against :func:`random_deletion_baseline` - an
    explanation no better than a random ordering is not an explanation.
    """
    normal_values = np.asarray(normal, dtype=np.float64)
    abnormal_values = np.asarray(abnormal, dtype=np.float64)
    index_of = {column.name: position for position, column in enumerate(columns)}

    with np.errstate(invalid="ignore"):
        medians = np.nanmedian(normal_values, axis=0)
    medians = np.nan_to_num(medians, nan=0.0)

    order = [name for name in ranking if name in index_of]
    scores: list[float] = []
    patched = abnormal_values.copy()

    for k in range(max_k + 1):
        if k > 0:
            if k - 1 >= len(order):
                # The method named fewer columns than k. Nothing more to remove,
                # so the score stops changing rather than being undefined.
                scores.append(scores[-1])
                continue
            position = index_of[order[k - 1]]
            patched[:, position] = medians[position]
        scores.append(system_anomaly_score(normal_values, patched))

    start = scores[0]
    normalised = (
        tuple(score / start for score in scores)
        if start > 0
        else tuple(0.0 for _ in scores)
    )
    return DeletionCurve(
        scores=tuple(scores),
        normalised=normalised,
        auc=float(np.mean(normalised)),
    )


def random_deletion_baseline(
    normal: npt.ArrayLike,
    abnormal: npt.ArrayLike,
    columns: Sequence[ColumnInfo],
    max_k: int = 10,
    repeats: int = 10,
    seed: int = 42,
) -> float:
    """The deletion area a method would get by guessing, averaged over orderings.

    ``docs/08`` section 4 asks for ten random orders. Without this number the
    deletion area means nothing: whether 0.6 is good depends entirely on what
    chance would have scored.
    """
    rng = np.random.default_rng(seed)
    names = [column.name for column in columns]
    areas = []
    for _ in range(repeats):
        shuffled = list(rng.permutation(names))
        areas.append(
            deletion_faithfulness(normal, abnormal, columns, shuffled, max_k).auc
        )
    return float(np.mean(areas))


def topk_jaccard(first: Sequence[str], second: Sequence[str], k: int = 5) -> float:
    """How much two top-k lists overlap: shared items over total distinct items.

    Used for stability - the same case, scored again under a slightly different
    window or seed, should produce a similar explanation. An explanation that
    changes when nothing important changed cannot be trusted, however accurate it
    happens to be on average.
    """
    if k < 1:
        raise ValueError(f"k must be at least 1, got {k}")
    left, right = set(first[:k]), set(second[:k])
    if not left and not right:
        return 1.0
    union = left | right
    return float(len(left & right) / len(union)) if union else 1.0


def kendall_tau(first: Sequence[str], second: Sequence[str]) -> float | None:
    """Rank correlation between two orderings, over the services both contain.

    1 means identical order, -1 exactly reversed, 0 unrelated. Returns None when
    fewer than two services are shared, where the measure is undefined rather
    than zero.
    """
    from scipy.stats import kendalltau

    shared = [name for name in first if name in set(second)]
    if len(shared) < 2:
        return None

    first_rank = {name: position for position, name in enumerate(first)}
    second_rank = {name: position for position, name in enumerate(second)}
    statistic = kendalltau(
        [first_rank[name] for name in shared], [second_rank[name] for name in shared]
    ).statistic
    return None if np.isnan(statistic) else float(statistic)


def compactness(scores: Mapping[str, float], fraction: float = 0.8) -> int:
    """How many indicators are needed to cover ``fraction`` of the score mass.

    A short explanation is worth more than a long one: twenty metrics ranked by a
    number is a list, not an explanation. Only positive scores count, since a
    negative or zero contribution explains nothing.
    """
    if not 0 < fraction <= 1:
        raise ValueError(f"fraction must be between 0 and 1, got {fraction}")

    positive = sorted((value for value in scores.values() if value > 0), reverse=True)
    total = sum(positive)
    if total <= 0:
        return 0

    running = 0.0
    for count, value in enumerate(positive, start=1):
        running += value
        if running >= fraction * total:
            return count
    return len(positive)


# --- helpers ----------------------------------------------------------------


def _as_rank(rank: Rank | int | None) -> Rank | None:
    """Accept a Rank, a plain 1-based integer, or None."""
    if rank is None or isinstance(rank, Rank):
        return rank
    return Rank(best=int(rank))
