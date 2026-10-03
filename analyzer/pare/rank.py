"""Turning per-column scores into an answer: who is to blame, and who is not.

Three jobs:

* **Rank the services.** A service is as bad as its worst metric, so its score is
  the largest self-score among its columns.
* **Decide whether anything is wrong at all.** If the leader is not far enough
  above normal, the honest answer is "nothing clear", not whoever came first.
* **Give every service a role.** CAUSE, SYMPTOM, ALSO_ABNORMAL or NORMAL. The
  roles are what the explanation text and the call-graph colours are built from,
  and the SYMPTOM role is the point of the whole project: a service that looks
  bad but whose trouble its callees account for.

Spec: ``docs/05_PYTHON_ANALYZER_SPEC.md`` section 3, steps 4 and 5.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pare.config import PareConfig
from pare.graph import CallGraph
from pare.residual import ColumnResidual

# The verdict, from docs/06 section 3.
ROOT_CAUSE_FOUND = "ROOT_CAUSE_FOUND"
NO_CLEAR_CAUSE = "NO_CLEAR_CAUSE"

# Roles, in the strict precedence order they are assigned in.
CAUSE = "CAUSE"
SYMPTOM = "SYMPTOM"
ALSO_ABNORMAL = "ALSO_ABNORMAL"
NORMAL = "NORMAL"


@dataclass(frozen=True)
class ServiceRanking:
    """One service's place in the answer."""

    service: str
    rank: int
    score: float
    """The ranking number: how much of this service's trouble is its own."""

    marginal_score: float
    """How bad it merely looks. Shown next to ``score`` so a reader can see the
    gap, which is the whole argument of the method."""

    inherited_fraction: float
    top_indicator: str | None
    role: str
    explained_by: str | None


@dataclass(frozen=True)
class IndicatorRanking:
    """One column's place in the answer."""

    column: str
    service: str
    metric: str
    rank: int
    self_score: float
    marginal_score: float
    inherited_fraction: float


@dataclass(frozen=True)
class Ranking:
    services: tuple[ServiceRanking, ...]
    indicators: tuple[IndicatorRanking, ...]
    verdict: str

    @property
    def top_service(self) -> str | None:
        return self.services[0].service if self.services else None

    @property
    def top_indicator(self) -> str | None:
        """The fine-grained answer: the worst column inside the leading service."""
        if not self.services:
            return None
        return self.services[0].top_indicator


def rank_all(
    residuals: Sequence[ColumnResidual],
    graph: CallGraph | None = None,
    config: PareConfig | None = None,
) -> Ranking:
    """Rank services and indicators, decide the verdict, and assign roles."""
    settings = config or PareConfig()
    if not residuals:
        return Ranking(services=(), indicators=(), verdict=NO_CLEAR_CAUSE)

    by_service = _group(residuals)
    scores = {
        service: _service_score(items, settings.service_agg)
        for service, items in by_service.items()
    }
    marginals = {
        service: max(item.marginal_score for item in items)
        for service, items in by_service.items()
    }

    order = sorted(scores, key=lambda service: (-scores[service], service))
    if settings.traversal and graph is not None and not graph.is_empty:
        order = traversal_rank(order, scores, marginals, graph)

    verdict = (
        ROOT_CAUSE_FOUND
        if scores[order[0]] >= settings.min_cause_score
        else NO_CLEAR_CAUSE
    )

    services: list[ServiceRanking] = []
    for position, service in enumerate(order, start=1):
        items = by_service[service]
        best = max(items, key=lambda item: item.self_score)
        services.append(
            ServiceRanking(
                service=service,
                rank=position,
                score=scores[service],
                marginal_score=marginals[service],
                inherited_fraction=best.inherited_fraction,
                top_indicator=best.column,
                role=_role(
                    is_first=position == 1,
                    verdict=verdict,
                    marginal=marginals[service],
                    inherited=best.inherited_fraction,
                    settings=settings,
                ),
                explained_by=best.explained_by,
            )
        )

    indicators = rank_indicators(residuals, settings.top_k)
    return Ranking(services=tuple(services), indicators=indicators, verdict=verdict)


def rank_indicators(
    residuals: Sequence[ColumnResidual], top_k: int
) -> tuple[IndicatorRanking, ...]:
    """The columns, worst first, cut to ``top_k``.

    Sorted by name within equal scores so the output is stable run to run, which
    matters for reproducibility and for diffing results.
    """
    ordered = sorted(residuals, key=lambda item: (-item.self_score, item.column))
    return tuple(
        IndicatorRanking(
            column=item.column,
            service=item.service,
            metric=item.metric,
            rank=position,
            self_score=item.self_score,
            marginal_score=item.marginal_score,
            inherited_fraction=item.inherited_fraction,
        )
        for position, item in enumerate(ordered[: max(top_k, 1)], start=1)
    )


def traversal_rank(
    order: Sequence[str],
    scores: dict[str, float],
    marginals: dict[str, float],
    graph: CallGraph,
) -> list[str]:
    """Walk down the call graph from the loudest service to the real source.

    Inspired by Orchard et al. 2025. Start where the noise is - the service with
    the highest marginal score, which is usually a symptom - then keep stepping to
    whichever callee has a higher self-score than where you are standing. You stop
    at the service whose trouble nothing downstream explains.

    Walking *down* is the whole point: an edge runs caller to callee, and a fault
    travels the other way, so following callees means walking back towards the
    source.

    The walk cannot loop: it only ever moves to a strictly higher self-score, and
    visited services are remembered as well, so a cyclic graph still terminates.
    """
    if not order:
        return list(order)

    current = max(marginals, key=lambda service: (marginals[service], service))
    seen = {current}

    while True:
        callees = [child for child in graph.children(current) if child in scores]
        if not callees:
            break
        best = max(callees, key=lambda child: (scores[child], child))
        if scores[best] <= scores[current] or best in seen:
            break
        current = best
        seen.add(current)

    rest = [service for service in order if service != current]
    return [current, *rest]


def assign_roles(
    services: Sequence[ServiceRanking], config: PareConfig | None = None
) -> tuple[ServiceRanking, ...]:
    """Re-assign roles to an existing ranking. Exposed for tests and for the
    ablation engines, which share the rule."""
    settings = config or PareConfig()
    verdict = (
        ROOT_CAUSE_FOUND
        if services and services[0].score >= settings.min_cause_score
        else NO_CLEAR_CAUSE
    )
    return tuple(
        ServiceRanking(
            service=item.service,
            rank=item.rank,
            score=item.score,
            marginal_score=item.marginal_score,
            inherited_fraction=item.inherited_fraction,
            top_indicator=item.top_indicator,
            role=_role(
                is_first=item.rank == 1,
                verdict=verdict,
                marginal=item.marginal_score,
                inherited=item.inherited_fraction,
                settings=settings,
            ),
            explained_by=item.explained_by,
        )
        for item in services
    )


# --- the pieces -------------------------------------------------------------


def _role(
    is_first: bool,
    verdict: str,
    marginal: float,
    inherited: float,
    settings: PareConfig,
) -> str:
    """The first role a service qualifies for, in strict order.

    Because the order is strict a service has exactly one role, and when the
    verdict is NO_CLEAR_CAUSE the leader simply falls through to whichever of the
    remaining roles fits - nobody is accused.
    """
    if is_first and verdict == ROOT_CAUSE_FOUND:
        return CAUSE
    if marginal >= settings.symptom_min_marginal:
        if inherited >= settings.symptom_min_inherited:
            return SYMPTOM
        return ALSO_ABNORMAL
    return NORMAL


def _service_score(items: Sequence[ColumnResidual], how: str) -> float:
    """A service is as bad as its worst metric, or the mean of its worst two."""
    scores = sorted((item.self_score for item in items), reverse=True)
    if not scores:
        return 0.0
    if how == "top2mean" and len(scores) >= 2:
        return float((scores[0] + scores[1]) / 2.0)
    return float(scores[0])


def _group(residuals: Sequence[ColumnResidual]) -> dict[str, list[ColumnResidual]]:
    grouped: dict[str, list[ColumnResidual]] = {}
    for item in residuals:
        grouped.setdefault(item.service, []).append(item)
    return grouped
