"""In-memory spatial index over all fuel stations, built once at process startup.

Rebuilding scipy's cKDTree from scratch (~6-7k points) takes single-digit
milliseconds, so a full reload is cheap enough to redo after every price
update rather than mutating in place. Coordinates and prices are swapped
atomically under a lock so an in-flight query never sees a torn read.
"""

from __future__ import annotations

import threading

import numpy as np
from scipy.spatial import cKDTree

MILES_PER_DEGREE_LAT = 69.172


def project(
    latitude: np.ndarray, longitude: np.ndarray, reference_latitude: float | None = None
) -> np.ndarray:
    """Equirectangular projection (lng scaled by cos(lat)) for cheap planar distance queries.

    `reference_latitude` must be the SAME value across every point cloud being
    compared in one distance/KDTree computation (e.g. a route's points and the
    stations being matched against it) — each point contributing its own
    latitude to the cos() scale factor breaks the metric consistency of the
    shared coordinate space: two points at different latitudes end up on
    different local scales, so "nearest in projected space" can disagree with
    "nearest in real miles." Defaults to the mean latitude of this call's own
    points, which is only correct when the caller passes one unified point set.
    """
    if reference_latitude is None:
        reference_latitude = float(np.mean(latitude))
    x = longitude * np.cos(np.radians(reference_latitude))
    y = latitude
    return np.column_stack([x, y])


class SpatialIndex:
    _lock = threading.RLock()

    station_ids: np.ndarray | None = None
    latitudes: np.ndarray | None = None
    longitudes: np.ndarray | None = None
    coords: np.ndarray | None = None
    prices: np.ndarray | None = None
    tree: cKDTree | None = None
    price_version: int = 0

    @classmethod
    def load(cls) -> None:
        """(Re)build the tree and price array from the current FuelStation table."""
        from routing.models import FuelStation

        rows = list(FuelStation.objects.values_list("id", "latitude", "longitude", "current_price"))

        if rows:
            ids, lats, lngs, prices = (np.array(col) for col in zip(*rows, strict=True))
            lats = lats.astype(np.float64)
            lngs = lngs.astype(np.float64)
            prices = prices.astype(np.float64)
            coords = project(lats, lngs)
            tree = cKDTree(coords)
        else:
            ids = np.array([], dtype=np.int64)
            lats = np.array([], dtype=np.float64)
            lngs = np.array([], dtype=np.float64)
            prices = np.array([], dtype=np.float64)
            coords = np.empty((0, 2), dtype=np.float64)
            tree = None

        with cls._lock:
            cls.station_ids = ids
            cls.latitudes = lats
            cls.longitudes = lngs
            cls.coords = coords
            cls.prices = prices
            cls.tree = tree
            cls.price_version += 1

    @classmethod
    def is_loaded(cls) -> bool:
        return cls.station_ids is not None

    @classmethod
    def station_count(cls) -> int:
        return 0 if cls.station_ids is None else len(cls.station_ids)
