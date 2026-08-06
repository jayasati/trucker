import numpy as np
import pytest

from routing.services.corridor import (
    cumulative_miles,
    densify_route,
    downsample_route,
    haversine_miles,
    match_stations,
)
from routing.spatial_index import MILES_PER_DEGREE_LAT

# A short north-south route along a fixed meridian: easy to reason about
# distances since 1 degree of latitude is ~69 miles regardless of longitude.
ROUTE_LNG = -100.0
ROUTE_LATS = np.arange(35.0, 36.01, 0.1)  # 11 points, ~6.9 mi apart
ROUTE_POINTS = np.column_stack([ROUTE_LATS, np.full_like(ROUTE_LATS, ROUTE_LNG)])


def test_haversine_miles_same_point_is_zero():
    result = haversine_miles(np.array([35.0]), np.array([-100.0]), np.array([35.0]), np.array([-100.0]))
    assert result[0] == pytest.approx(0.0, abs=1e-9)


def test_haversine_miles_one_degree_latitude_is_about_69_miles():
    result = haversine_miles(np.array([35.0]), np.array([-100.0]), np.array([36.0]), np.array([-100.0]))
    assert result[0] == pytest.approx(69.0, rel=0.02)


def test_cumulative_miles_matches_segment_sum():
    cum = cumulative_miles(ROUTE_POINTS)
    assert cum[0] == 0.0
    assert len(cum) == len(ROUTE_POINTS)
    assert np.all(np.diff(cum) > 0)  # strictly increasing along a one-directional route
    # Total should be close to 1 degree of latitude worth of miles.
    assert cum[-1] == pytest.approx(69.0, rel=0.02)


def test_cumulative_miles_handles_single_point():
    single = np.array([[35.0, -100.0]])
    assert list(cumulative_miles(single)) == [0.0]


def test_downsample_route_keeps_first_and_last_point():
    kept_points, kept_cum = downsample_route(ROUTE_POINTS, cumulative_miles(ROUTE_POINTS), spacing_miles=2.0)
    assert tuple(kept_points[0]) == tuple(ROUTE_POINTS[0])
    assert tuple(kept_points[-1]) == tuple(ROUTE_POINTS[-1])


def test_downsample_route_reduces_dense_points():
    # 200 points packed into the same short stretch: far denser than 1-per-2-miles.
    dense_lats = np.linspace(35.0, 35.2, 200)
    dense_points = np.column_stack([dense_lats, np.full_like(dense_lats, ROUTE_LNG)])
    cum = cumulative_miles(dense_points)

    kept_points, kept_cum = downsample_route(dense_points, cum, spacing_miles=2.0)

    assert len(kept_points) < len(dense_points)
    assert tuple(kept_points[0]) == tuple(dense_points[0])
    assert tuple(kept_points[-1]) == tuple(dense_points[-1])


def test_match_stations_on_route_station_has_zero_detour_and_correct_mile_marker():
    # Station sits exactly on route_points[5] (lat=35.5).
    station_lat = ROUTE_LATS[5]
    expected_mile_marker = cumulative_miles(ROUTE_POINTS)[5]

    matches = match_stations(
        ROUTE_POINTS,
        station_ids=np.array([1]),
        station_latitudes=np.array([station_lat]),
        station_longitudes=np.array([ROUTE_LNG]),
        detour_radius_miles=10.0,
    )

    assert len(matches) == 1
    assert matches[0].station_id == 1
    assert matches[0].detour_miles == pytest.approx(0.0, abs=1e-6)
    assert matches[0].miles_from_start == pytest.approx(expected_mile_marker, abs=1e-6)


def test_match_stations_computes_detour_miles_for_off_route_station():
    station_lat = ROUTE_LATS[5]
    delta_lng = 0.05  # station sits east of the route at the same latitude
    station_lng = ROUTE_LNG + delta_lng

    expected_detour = abs(delta_lng) * np.cos(np.radians(station_lat)) * MILES_PER_DEGREE_LAT

    matches = match_stations(
        ROUTE_POINTS,
        station_ids=np.array([2]),
        station_latitudes=np.array([station_lat]),
        station_longitudes=np.array([station_lng]),
        detour_radius_miles=10.0,
    )

    assert len(matches) == 1
    assert matches[0].detour_miles == pytest.approx(expected_detour, rel=1e-3)


def test_match_stations_excludes_station_outside_radius():
    station_lat = ROUTE_LATS[5]
    far_lng = ROUTE_LNG + 1.0  # ~55+ miles off the route at this latitude

    matches = match_stations(
        ROUTE_POINTS,
        station_ids=np.array([3]),
        station_latitudes=np.array([station_lat]),
        station_longitudes=np.array([far_lng]),
        detour_radius_miles=10.0,
    )

    assert matches == []


def test_match_stations_returns_empty_when_no_stations():
    matches = match_stations(
        ROUTE_POINTS,
        station_ids=np.array([]),
        station_latitudes=np.array([]),
        station_longitudes=np.array([]),
        detour_radius_miles=10.0,
    )
    assert matches == []


def test_match_stations_sorted_by_miles_from_start():
    lats = np.array([ROUTE_LATS[8], ROUTE_LATS[2], ROUTE_LATS[5]])
    matches = match_stations(
        ROUTE_POINTS,
        station_ids=np.array([100, 200, 300]),
        station_latitudes=lats,
        station_longitudes=np.full(3, ROUTE_LNG),
        detour_radius_miles=10.0,
    )

    assert [m.station_id for m in matches] == [200, 300, 100]
    assert [m.miles_from_start for m in matches] == sorted(m.miles_from_start for m in matches)


# --- densify_route: guards against sparse OSRM "simplified" geometry --------


def test_densify_route_caps_segment_length():
    sparse = np.array([[35.0, -100.0], [36.0, -100.0]])  # ~69mi apart, one segment

    dense = densify_route(sparse, max_segment_miles=2.0)

    seg_miles = haversine_miles(dense[:-1, 0], dense[:-1, 1], dense[1:, 0], dense[1:, 1])
    assert np.all(seg_miles <= 2.0 + 1e-6)
    assert tuple(dense[0]) == tuple(sparse[0])
    assert tuple(dense[-1]) == tuple(sparse[-1])


def test_densify_route_leaves_already_dense_segments_untouched():
    close_points = np.array([[35.0, -100.0], [35.01, -100.0]])  # <1mi apart
    dense = densify_route(close_points, max_segment_miles=2.0)
    assert len(dense) == 2


def test_match_stations_finds_station_between_sparse_route_vertices():
    # Mimics OSRM's "simplified" geometry: only 2 vertices, tens of miles apart.
    # A station near the midpoint should still be matched once the route is
    # densified internally -- a bare 2-point KDTree would miss it entirely,
    # since the nearest of only 2 vertices is far more than 10mi away.
    sparse_route = np.array([[35.0, -100.0], [36.0, -100.0]])  # ~69mi apart
    midpoint_lat = 35.5

    matches = match_stations(
        sparse_route,
        station_ids=np.array([1]),
        station_latitudes=np.array([midpoint_lat]),
        station_longitudes=np.array([-100.0]),
        detour_radius_miles=10.0,
    )

    assert len(matches) == 1
    assert matches[0].detour_miles < 1.0
    assert matches[0].miles_from_start == pytest.approx(34.5, rel=0.05)


def test_match_stations_uses_consistent_projection_across_point_clouds():
    # Regression test: projecting the route and the stations with different
    # per-point latitude scale factors can rank a station that's genuinely
    # farther away (in real miles) as "closer" than one sitting exactly on
    # the route, because each point's own cos(lat) distorts the shared
    # coordinate space differently. A station placed exactly on the route
    # must always win over an off-route station at a nearby latitude.
    on_route_lat = ROUTE_LATS[5]
    off_route_lat = ROUTE_LATS[4]  # a full route-spacing away, not on the path

    matches = match_stations(
        ROUTE_POINTS,
        station_ids=np.array([1, 2]),
        station_latitudes=np.array([on_route_lat, off_route_lat]),
        station_longitudes=np.array([ROUTE_LNG, ROUTE_LNG + 0.05]),
        detour_radius_miles=10.0,
    )

    by_id = {m.station_id: m for m in matches}
    assert by_id[1].detour_miles == pytest.approx(0.0, abs=1e-6)
    assert by_id[1].detour_miles < by_id[2].detour_miles
