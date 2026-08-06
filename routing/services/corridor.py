"""Match fuel stations to a route corridor: which stations are near the route,
at what mile-marker, and how far off the highway they sit.

The heavy lifting is one batched `cKDTree.query` (see `match_stations`): rather
than build a tree over ~6,700 stations and probe it once per route point, we
build a small tree over the (downsampled) route and query it with every
station's coordinates at once. That gives, for every station, both its
nearest-route-point distance (the detour) and that point's cumulative mileage
(the mile-marker) in a single vectorized call.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from routing.spatial_index import MILES_PER_DEGREE_LAT, SpatialIndex, project

EARTH_RADIUS_MILES = 3958.8
DOWNSAMPLE_SPACING_MILES = 2.0


@dataclass(frozen=True)
class CorridorStation:
    station_id: int
    miles_from_start: float
    detour_miles: float


def haversine_miles(
    lat1: np.ndarray, lng1: np.ndarray, lat2: np.ndarray, lng2: np.ndarray
) -> np.ndarray:
    """Vectorized great-circle distance in miles between paired points."""
    lat1r, lng1r, lat2r, lng2r = (np.radians(a) for a in (lat1, lng1, lat2, lng2))
    dlat = lat2r - lat1r
    dlng = lng2r - lng1r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def densify_route(route_points: np.ndarray, max_segment_miles: float = DOWNSAMPLE_SPACING_MILES) -> np.ndarray:
    """Linearly interpolate extra vertices so no gap between consecutive points
    exceeds `max_segment_miles`.

    OSRM's simplified geometry (used for the response/latency budget — see
    osrm.py) can have segments many miles long on straight highway stretches.
    Matching stations against that directly means measuring straight-line
    distance to whichever sparse vertex happens to be nearest, which can miss
    real stations sitting between vertices. Interpolating first guarantees the
    nearest-point search below is never coarser than the route's actual shape.
    """
    if len(route_points) < 2:
        return route_points

    seg_miles = haversine_miles(
        route_points[:-1, 0], route_points[:-1, 1], route_points[1:, 0], route_points[1:, 1]
    )

    pieces = [route_points[:1]]
    for i, miles in enumerate(seg_miles):
        start, end = route_points[i], route_points[i + 1]
        if miles > max_segment_miles:
            extra_count = int(np.ceil(miles / max_segment_miles)) - 1
            t = np.linspace(0.0, 1.0, extra_count + 2)[1:-1].reshape(-1, 1)
            pieces.append(start + t * (end - start))
        pieces.append(end.reshape(1, 2))

    return np.vstack(pieces)


def cumulative_miles(route_points: np.ndarray) -> np.ndarray:
    """route_points: (N, 2) array of (lat, lng). Returns (N,) cumulative miles from point 0."""
    if len(route_points) < 2:
        return np.zeros(len(route_points))
    seg_miles = haversine_miles(
        route_points[:-1, 0], route_points[:-1, 1], route_points[1:, 0], route_points[1:, 1]
    )
    return np.concatenate([[0.0], np.cumsum(seg_miles)])


def downsample_route(
    route_points: np.ndarray, cum_miles: np.ndarray, spacing_miles: float = DOWNSAMPLE_SPACING_MILES
) -> tuple[np.ndarray, np.ndarray]:
    """Keep ~1 point per `spacing_miles`, always including the first and last point."""
    if len(route_points) <= 2:
        return route_points, cum_miles

    bucket = np.floor(cum_miles / spacing_miles).astype(np.int64)
    _, first_index_per_bucket = np.unique(bucket, return_index=True)
    keep = np.sort(first_index_per_bucket)
    if keep[-1] != len(route_points) - 1:
        keep = np.append(keep, len(route_points) - 1)
    return route_points[keep], cum_miles[keep]


def match_stations(
    route_points: np.ndarray,
    station_ids: np.ndarray,
    station_latitudes: np.ndarray,
    station_longitudes: np.ndarray,
    detour_radius_miles: float,
) -> list[CorridorStation]:
    """Pure spatial join: which of the given stations lie within `detour_radius_miles`
    of the route, and where. No DB/settings access, so it's directly unit-testable.
    """
    if len(station_ids) == 0 or len(route_points) == 0:
        return []

    route_points = np.asarray(route_points, dtype=np.float64)
    route_points = densify_route(route_points)
    cum_miles = cumulative_miles(route_points)
    down_points, down_cum_miles = downsample_route(route_points, cum_miles)

    # One shared reference latitude for both point clouds in this comparison —
    # see project()'s docstring for why using each point's own latitude breaks
    # nearest-neighbor correctness across two separately-projected clouds.
    reference_latitude = float(np.mean(down_points[:, 0]))

    route_projected = project(down_points[:, 0], down_points[:, 1], reference_latitude)
    route_tree = cKDTree(route_projected)

    station_projected = project(
        np.asarray(station_latitudes, dtype=np.float64),
        np.asarray(station_longitudes, dtype=np.float64),
        reference_latitude,
    )
    distances_deg, nearest_point_index = route_tree.query(station_projected, k=1, workers=-1)
    distances_miles = distances_deg * MILES_PER_DEGREE_LAT

    within_radius = distances_miles <= detour_radius_miles
    matched_ids = np.asarray(station_ids)[within_radius]
    matched_mile_markers = down_cum_miles[nearest_point_index[within_radius]]
    matched_detours = distances_miles[within_radius]

    stations = [
        CorridorStation(station_id=int(sid), miles_from_start=float(mile), detour_miles=float(detour))
        for sid, mile, detour in zip(matched_ids, matched_mile_markers, matched_detours, strict=True)
    ]
    stations.sort(key=lambda s: s.miles_from_start)
    return stations


def match_stations_to_corridor(
    route_points: list[tuple[float, float]], detour_radius_miles: float | None = None
) -> list[CorridorStation]:
    """Match against the live, in-process station index (see routing.spatial_index)."""
    from django.conf import settings

    radius = detour_radius_miles if detour_radius_miles is not None else settings.DETOUR_RADIUS_MILES

    if not SpatialIndex.is_loaded():
        SpatialIndex.load()

    return match_stations(
        np.asarray(route_points, dtype=np.float64),
        SpatialIndex.station_ids,
        SpatialIndex.latitudes,
        SpatialIndex.longitudes,
        radius,
    )
