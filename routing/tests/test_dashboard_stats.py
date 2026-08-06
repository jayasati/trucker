import pytest

from routing.models import FuelStation
from routing.services.dashboard_stats import (
    OTHER_BRAND,
    bucket_price,
    compute_dashboard_stats,
    normalize_brand,
)


# --- normalize_brand: pure function -----------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("PILOT TRAVEL CENTER #1243", "Pilot Flying J"),
        ("FLYING J TRAVEL PLAZA", "Pilot Flying J"),
        ("LOVES TRAVEL STOP #337", "Love's"),
        ("Love's Travel Stop #826", "Love's"),
        ("TA SEYMOUR TRAVEL CENTER", "TA / Petro"),
        ("PETRO STOPPING CENTER #348", "TA / Petro"),
        ("KUM & GO #0201", "Kum & Go"),
        ("CIRCLE K #2612042", "Circle K"),
        ("7-ELEVEN #1000", "7-Eleven"),
        ("WOODSHED OF BIG CABIN", OTHER_BRAND),
        ("WEIRD LOCAL TRUCK STOP", OTHER_BRAND),
    ],
)
def test_normalize_brand(name, expected):
    assert normalize_brand(name) == expected


# --- bucket_price: pure function --------------------------------------------


def test_bucket_price_below_floor():
    assert bucket_price(2.10) == "under $2.50"


def test_bucket_price_at_floor():
    assert bucket_price(2.50) == "$2.50–2.75"


def test_bucket_price_mid_bin():
    assert bucket_price(3.10) == "$3.00–3.25"


def test_bucket_price_just_under_ceiling():
    assert bucket_price(4.74) == "$4.50–4.75"


def test_bucket_price_at_and_above_ceiling():
    assert bucket_price(4.75) == "$4.75+"
    assert bucket_price(6.40) == "$4.75+"


# --- compute_dashboard_stats: DB-backed aggregation -------------------------


def _make_station(opis_id, price, state, city="Anytown", name="TEST STOP", geocode_source="city"):
    return FuelStation.objects.create(
        opis_id=opis_id,
        name=name,
        address="I-1, EXIT 1",
        city=city,
        state=state,
        rack_id=1,
        current_price=price,
        latitude=36.0,
        longitude=-97.0,
        geocode_source=geocode_source,
    )


@pytest.mark.django_db
def test_compute_dashboard_stats_empty_table_returns_zeros():
    stats = compute_dashboard_stats()
    assert stats.total_stations == 0
    assert stats.cheapest_states == []
    assert stats.top_brands == []


@pytest.mark.django_db
def test_compute_dashboard_stats_basic_aggregates():
    _make_station(1, "3.00", "OK", name="LOVES TRAVEL STOP #1")
    _make_station(2, "4.00", "TX", name="PILOT TRAVEL CENTER #2")
    _make_station(3, "5.00", "TX", name="RANDOM LOCAL STOP", geocode_source="state_centroid")

    stats = compute_dashboard_stats(min_state_sample=1)

    assert stats.total_stations == 3
    assert stats.distinct_states == 2
    assert stats.min_price == 3.00
    assert stats.max_price == 5.00
    assert stats.avg_price == pytest.approx(4.00)
    assert stats.city_geocoded == 2
    assert stats.state_centroid_geocoded == 1
    assert stats.city_geocoded_pct == pytest.approx(200 / 3)


@pytest.mark.django_db
def test_compute_dashboard_stats_state_ranking_respects_min_sample():
    # OK has only 1 station: excluded when min_state_sample=2.
    _make_station(1, "2.50", "OK")
    _make_station(2, "3.00", "TX")
    _make_station(3, "3.50", "TX")

    stats = compute_dashboard_stats(min_state_sample=2, top_n_states=5)

    states_seen = {s.state for s in stats.cheapest_states}
    assert states_seen == {"TX"}


@pytest.mark.django_db
def test_compute_dashboard_stats_cheapest_and_priciest_states_ordering():
    _make_station(1, "2.00", "OK")
    _make_station(2, "2.00", "OK")
    _make_station(3, "5.00", "WA")
    _make_station(4, "5.00", "WA")

    stats = compute_dashboard_stats(min_state_sample=2, top_n_states=5)

    assert stats.cheapest_states[0].state == "OK"
    assert stats.priciest_states[0].state == "WA"


@pytest.mark.django_db
def test_compute_dashboard_stats_top_brands_counts_and_excludes_other():
    _make_station(1, "3.00", "OK", name="LOVES TRAVEL STOP #1")
    _make_station(2, "3.20", "OK", name="LOVES TRAVEL STOP #2")
    _make_station(3, "3.10", "OK", name="SOME UNBRANDED STOP")

    stats = compute_dashboard_stats(top_n_brands=5)

    brands = {b.brand: b for b in stats.top_brands}
    assert brands["Love's"].count == 2
    assert brands["Love's"].avg_price == pytest.approx(3.10)
    assert OTHER_BRAND not in brands


@pytest.mark.django_db
def test_compute_dashboard_stats_histogram_sums_to_total():
    for i, price in enumerate(["2.10", "2.60", "3.10", "4.80", "6.00"], start=1):
        _make_station(i, price, "OK")

    stats = compute_dashboard_stats()

    assert sum(b.count for b in stats.price_histogram) == 5
    by_label = {b.label: b.count for b in stats.price_histogram}
    assert by_label["under $2.50"] == 1
    assert by_label["$4.75+"] == 2


@pytest.mark.django_db
def test_compute_dashboard_stats_cheapest_stations_sorted_ascending():
    _make_station(1, "5.00", "OK", name="EXPENSIVE")
    _make_station(2, "2.50", "OK", name="CHEAPEST")
    _make_station(3, "3.50", "OK", name="MIDDLE")

    stats = compute_dashboard_stats(top_n_cheap_stations=2)

    assert [s.name for s in stats.cheapest_stations] == ["CHEAPEST", "MIDDLE"]
