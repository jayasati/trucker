"""Full (non-truncated) breakdowns backing the Analytics page.

dashboard_stats.py computes a curated top-N summary for the Dashboard; this
module computes the complete versions of the same underlying data -- every
state, every brand, plus the price percentiles that don't fit on a summary
card -- reusing its brand normalization so the two pages agree with each
other.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Avg, Count, Max, Min

from routing.models import FuelStation
from routing.services.dashboard_stats import OTHER_BRAND, normalize_brand

DEFAULT_PERCENTILES = (10, 25, 50, 75, 90, 99)


@dataclass(frozen=True)
class PercentileStat:
    label: str
    price: float


@dataclass(frozen=True)
class StateBreakdown:
    state: str
    count: int
    avg_price: float
    min_price: float
    max_price: float


@dataclass(frozen=True)
class BrandBreakdown:
    brand: str
    count: int
    avg_price: float
    min_price: float
    max_price: float


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(len(sorted_values) * pct / 100))
    return sorted_values[index]


def compute_percentiles(percentiles: tuple[int, ...] = DEFAULT_PERCENTILES) -> list[PercentileStat]:
    """Price percentiles across every tracked station, nearest-rank method."""
    prices = sorted(float(p) for p in FuelStation.objects.values_list("current_price", flat=True))
    return [PercentileStat(f"p{pct}", _percentile(prices, pct)) for pct in percentiles]


def compute_full_state_breakdown() -> list[StateBreakdown]:
    """Every state/province with at least one tracked station, cheapest first."""
    rows = FuelStation.objects.values("state").annotate(
        n=Count("id"), avg=Avg("current_price"), mn=Min("current_price"), mx=Max("current_price")
    ).order_by("avg")
    return [
        StateBreakdown(row["state"], row["n"], float(row["avg"]), float(row["mn"]), float(row["mx"]))
        for row in rows
    ]


def compute_full_brand_breakdown() -> list[BrandBreakdown]:
    """Every recognized brand plus an 'Independent / other' bucket, busiest first."""
    totals: dict[str, list[float]] = {}
    for name, price in FuelStation.objects.values_list("name", "current_price"):
        totals.setdefault(normalize_brand(name), []).append(float(price))

    breakdown = [
        BrandBreakdown(brand, len(prices), sum(prices) / len(prices), min(prices), max(prices))
        for brand, prices in totals.items()
        if brand != OTHER_BRAND
    ]
    breakdown.sort(key=lambda b: -b.count)

    if OTHER_BRAND in totals:
        prices = totals[OTHER_BRAND]
        breakdown.append(
            BrandBreakdown(OTHER_BRAND, len(prices), sum(prices) / len(prices), min(prices), max(prices))
        )

    return breakdown
