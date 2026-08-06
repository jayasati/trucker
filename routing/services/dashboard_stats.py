"""Real aggregate insights computed from the loaded FuelStation table.

Everything here is derived from actual station rows -- no fleet, driver, or
spend data exists anywhere in this system, so unlike the reference mockup
this dashboard only shows numbers that are true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.db.models import Avg, Count

from routing.models import FuelStation

MIN_STATE_SAMPLE = 20  # exclude states with too few stations for a meaningful average
HISTOGRAM_BIN_WIDTH = 0.25
HISTOGRAM_FLOOR = 2.50
HISTOGRAM_CEILING = 4.75

# Ordered (pattern, canonical name) pairs; first match wins. Station names in
# the source CSV are inconsistent ("PILOT TRAVEL CENTER" vs "PILOT TRAVEL
# CENTERS" vs bare "PILOT"), so this groups by regex rather than exact text.
_BRAND_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bLOVE.?S\b", re.I), "Love's"),
    (re.compile(r"\bPILOT\b|\bFLYING J\b", re.I), "Pilot Flying J"),
    (re.compile(r"\bT\s?A\b|\bPETRO\b", re.I), "TA / Petro"),
    (re.compile(r"\bCIRCLE K\b", re.I), "Circle K"),
    (re.compile(r"\bKWIK TRIP\b|\bKWIK STAR\b", re.I), "Kwik Trip / Star"),
    (re.compile(r"\bSPEEDWAY\b", re.I), "Speedway"),
    (re.compile(r"\bCASEY.?S\b", re.I), "Casey's"),
    (re.compile(r"\bQUIKTRIP\b", re.I), "QuikTrip"),
    (re.compile(r"\b7[\s-]?ELEVEN\b", re.I), "7-Eleven"),
    (re.compile(r"\bMAVERIK\b", re.I), "Maverik"),
    (re.compile(r"\bKUM\s*(?:&|AND)\s*GO\b", re.I), "Kum & Go"),
    (re.compile(r"\bALLSUPS?\b", re.I), "Allsup's"),
    (re.compile(r"\bSTRIPES\b", re.I), "Stripes"),
    (re.compile(r"\bQUARLES\b", re.I), "Quarles"),
]
OTHER_BRAND = "Independent / other"


def normalize_brand(station_name: str) -> str:
    """Map a raw station name to a canonical brand bucket, or OTHER_BRAND."""
    for pattern, canonical in _BRAND_PATTERNS:
        if pattern.search(station_name):
            return canonical
    return OTHER_BRAND


def bucket_price(price: float) -> str:
    """Bucket a price into a fixed-width histogram bin label.

    Bins run from HISTOGRAM_FLOOR to HISTOGRAM_CEILING; anything outside that
    range collapses into an under/over-flow bucket so the handful of extreme
    outliers (a few stations near $6.40) don't stretch the chart's axis.
    """
    if price < HISTOGRAM_FLOOR:
        return f"under ${HISTOGRAM_FLOOR:.2f}"
    if price >= HISTOGRAM_CEILING:
        return f"${HISTOGRAM_CEILING:.2f}+"
    bin_index = int((price - HISTOGRAM_FLOOR) / HISTOGRAM_BIN_WIDTH)
    lo = HISTOGRAM_FLOOR + bin_index * HISTOGRAM_BIN_WIDTH
    hi = lo + HISTOGRAM_BIN_WIDTH
    return f"${lo:.2f}–{hi:.2f}"


def _histogram_bucket_order() -> list[str]:
    labels = [f"under ${HISTOGRAM_FLOOR:.2f}"]
    bin_count = int(round((HISTOGRAM_CEILING - HISTOGRAM_FLOOR) / HISTOGRAM_BIN_WIDTH))
    for i in range(bin_count):
        lo = HISTOGRAM_FLOOR + i * HISTOGRAM_BIN_WIDTH
        hi = lo + HISTOGRAM_BIN_WIDTH
        labels.append(f"${lo:.2f}–{hi:.2f}")
    labels.append(f"${HISTOGRAM_CEILING:.2f}+")
    return labels


@dataclass(frozen=True)
class StateStat:
    state: str
    count: int
    avg_price: float


@dataclass(frozen=True)
class BrandStat:
    brand: str
    count: int
    avg_price: float


@dataclass(frozen=True)
class PriceBucket:
    label: str
    count: int


@dataclass(frozen=True)
class CheapStation:
    name: str
    city: str
    state: str
    price: float


@dataclass(frozen=True)
class DashboardStats:
    total_stations: int
    distinct_states: int
    avg_price: float
    min_price: float
    max_price: float
    median_price: float
    city_geocoded: int
    state_centroid_geocoded: int
    city_geocoded_pct: float
    cheapest_states: list[StateStat]
    priciest_states: list[StateStat]
    top_brands: list[BrandStat]
    price_histogram: list[PriceBucket]
    price_histogram_max: int
    cheapest_stations: list[CheapStation]


def compute_dashboard_stats(
    *,
    min_state_sample: int = MIN_STATE_SAMPLE,
    top_n_states: int = 5,
    top_n_brands: int = 8,
    top_n_cheap_stations: int = 12,
) -> DashboardStats:
    """Compute every dashboard metric from the current FuelStation table."""
    total_stations = FuelStation.objects.count()
    if total_stations == 0:
        return DashboardStats(0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0.0, [], [], [], [], 0, [])

    prices = sorted(float(p) for p in FuelStation.objects.values_list("current_price", flat=True))
    avg_price = sum(prices) / len(prices)
    median_price = prices[len(prices) // 2]

    geocode_counts = dict(
        FuelStation.objects.values_list("geocode_source").annotate(n=Count("id")).values_list("geocode_source", "n")
    )
    city_geocoded = geocode_counts.get("city", 0)
    state_centroid_geocoded = geocode_counts.get("state_centroid", 0)

    by_state = list(
        FuelStation.objects.values("state")
        .annotate(n=Count("id"), avg=Avg("current_price"))
        .filter(n__gte=min_state_sample)
        .order_by("avg")
    )
    state_stats = [StateStat(row["state"], row["n"], float(row["avg"])) for row in by_state]
    distinct_states = FuelStation.objects.values("state").distinct().count()

    brand_totals: dict[str, list[float]] = {}
    for name, price in FuelStation.objects.values_list("name", "current_price"):
        brand = normalize_brand(name)
        brand_totals.setdefault(brand, []).append(float(price))
    top_brands = sorted(
        (
            BrandStat(brand, len(prices_list), sum(prices_list) / len(prices_list))
            for brand, prices_list in brand_totals.items()
            if brand != OTHER_BRAND
        ),
        key=lambda b: -b.count,
    )[:top_n_brands]

    bucket_counts: dict[str, int] = {label: 0 for label in _histogram_bucket_order()}
    for price in prices:
        bucket_counts[bucket_price(price)] += 1
    price_histogram = [PriceBucket(label, bucket_counts[label]) for label in _histogram_bucket_order()]
    price_histogram_max = max(bucket_counts.values())

    cheapest_qs = FuelStation.objects.order_by("current_price")[:top_n_cheap_stations]
    cheapest_stations = [
        CheapStation(s.name, s.city, s.state, float(s.current_price)) for s in cheapest_qs
    ]

    return DashboardStats(
        total_stations=total_stations,
        distinct_states=distinct_states,
        avg_price=avg_price,
        min_price=prices[0],
        max_price=prices[-1],
        median_price=median_price,
        city_geocoded=city_geocoded,
        state_centroid_geocoded=state_centroid_geocoded,
        city_geocoded_pct=100.0 * city_geocoded / total_stations,
        cheapest_states=state_stats[:top_n_states],
        priciest_states=list(reversed(state_stats[-top_n_states:])),
        top_brands=top_brands,
        price_histogram=price_histogram,
        price_histogram_max=price_histogram_max,
        cheapest_stations=cheapest_stations,
    )
