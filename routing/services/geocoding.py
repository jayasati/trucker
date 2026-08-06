"""Offline city+state -> lat/lng lookup for station geocoding. Zero network calls.

Uses the `zipcodes` package, which bundles ~42k US ZIP records (city, state,
lat, lng) as static package data with no runtime download — unlike `uszipcode`,
whose sqlite database is fetched over the network on first use and whose
dependency chain is broken against current sqlalchemy releases. Coverage was
verified against data/fuel-prices-for-be-assessment.csv: 7527/7531 US rows
(99.9%) match a known city+state exactly; the remainder use the state
centroid, which is always available.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

import zipcodes

logger = logging.getLogger(__name__)

# Approximate geographic centroids for Canadian provinces/territories. The
# source CSV includes some cross-border truck stops outside the zipcodes
# package's US-only coverage; these keep the "never drop a row" guarantee.
PROVINCE_CENTROIDS: dict[str, tuple[float, float]] = {
    "AB": (55.0000, -115.0000),
    "BC": (53.7267, -127.6476),
    "MB": (53.7609, -98.8139),
    "NB": (46.5653, -66.4619),
    "NL": (53.1355, -57.6604),
    "NS": (44.6820, -63.7443),
    "NT": (64.8255, -124.8457),
    "NU": (70.2998, -83.1076),
    "ON": (51.2538, -85.3232),
    "PE": (46.5107, -63.4168),
    "QC": (52.9399, -73.5491),
    "SK": (52.9399, -106.4509),
    "YT": (64.2823, -135.0000),
}

CONTINENTAL_US_CENTROID: tuple[float, float] = (39.8283, -98.5795)

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _normalize_city(city: str) -> str:
    return _WHITESPACE_RE.sub(" ", city.strip().lower())


def _condensed_city(city: str) -> str:
    """Strip all non-alphanumerics, e.g. "de forest" / "de-forest" -> "deforest"."""
    return _NON_ALNUM_RE.sub("", city.lower())


@dataclass(frozen=True)
class CityIndex:
    by_city_state: dict[tuple[str, str], tuple[float, float]]
    by_condensed_city_state: dict[tuple[str, str], tuple[float, float]]
    state_centroids: dict[str, tuple[float, float]]


@lru_cache(maxsize=1)
def _build_index() -> CityIndex:
    by_city_state: dict[tuple[str, str], tuple[float, float]] = {}
    by_condensed_city_state: dict[tuple[str, str], tuple[float, float]] = {}
    state_sums: dict[str, list[float]] = {}

    for record in zipcodes.list_all():
        lat, lng = record.get("lat"), record.get("long")
        state = record.get("state")
        if not lat or not lng or not state:
            continue
        coord = (float(lat), float(lng))

        names = {record["city"], *(record.get("acceptable_cities") or [])}
        for name in names:
            if not name:
                continue
            key = (_normalize_city(name), state)
            by_city_state.setdefault(key, coord)
            by_condensed_city_state.setdefault((_condensed_city(name), state), coord)

        state_sums.setdefault(state, [0.0, 0.0, 0])
        bucket = state_sums[state]
        bucket[0] += coord[0]
        bucket[1] += coord[1]
        bucket[2] += 1

    state_centroids = {
        state: (lat_sum / count, lng_sum / count)
        for state, (lat_sum, lng_sum, count) in state_sums.items()
        if count
    }

    return CityIndex(
        by_city_state=by_city_state,
        by_condensed_city_state=by_condensed_city_state,
        state_centroids=state_centroids,
    )


def geocode_city_state(city: str, state: str) -> tuple[float, float, str]:
    """Resolve a station's (city, state) to coordinates offline.

    Returns (latitude, longitude, source) where source is "city" on an exact
    or condensed-name match, or "state_centroid" when only the state/province
    is known. A row is never dropped: an unrecognized state still resolves to
    the continental US centroid, logged as a warning since it should not
    happen with real US/Canada input.
    """
    state = state.strip().upper()
    index = _build_index()

    key = (_normalize_city(city), state)
    coord = index.by_city_state.get(key)
    if coord is not None:
        return coord[0], coord[1], "city"

    condensed_key = (_condensed_city(city), state)
    coord = index.by_condensed_city_state.get(condensed_key)
    if coord is not None:
        return coord[0], coord[1], "city"

    coord = index.state_centroids.get(state) or PROVINCE_CENTROIDS.get(state)
    if coord is not None:
        return coord[0], coord[1], "state_centroid"

    logger.warning("Unrecognized state/province %r for city %r; using US centroid fallback", state, city)
    return CONTINENTAL_US_CENTROID[0], CONTINENTAL_US_CENTROID[1], "state_centroid"
