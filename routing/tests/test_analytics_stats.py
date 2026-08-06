import pytest

from routing.models import FuelStation
from routing.services.analytics_stats import (
    compute_full_brand_breakdown,
    compute_full_state_breakdown,
    compute_percentiles,
)
from routing.services.dashboard_stats import OTHER_BRAND


def _make_station(opis_id, price, state, name="TEST STOP", city="Anytown"):
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
        geocode_source="city",
    )


# --- compute_percentiles -----------------------------------------------------


@pytest.mark.django_db
def test_percentiles_empty_table():
    result = compute_percentiles(percentiles=(50,))
    assert result[0].label == "p50"
    assert result[0].price == 0.0


@pytest.mark.django_db
def test_percentiles_nearest_rank():
    # 10 stations priced 1.00..10.00; p50 (index 5 of 10) -> 6.00 under nearest-rank.
    for i in range(1, 11):
        _make_station(i, f"{i}.00", "OK")

    result = {p.label: p.price for p in compute_percentiles(percentiles=(0, 50, 90, 100))}

    assert result["p0"] == pytest.approx(1.00)
    assert result["p50"] == pytest.approx(6.00)
    assert result["p100"] == pytest.approx(10.00)


# --- compute_full_state_breakdown --------------------------------------------


@pytest.mark.django_db
def test_full_state_breakdown_includes_single_station_states():
    _make_station(1, "5.00", "WY")  # only one station in this state
    _make_station(2, "3.00", "TX")
    _make_station(3, "3.50", "TX")

    result = compute_full_state_breakdown()
    states = {s.state: s for s in result}

    assert "WY" in states
    assert states["WY"].count == 1
    assert states["TX"].count == 2
    assert states["TX"].avg_price == pytest.approx(3.25)
    assert states["TX"].min_price == pytest.approx(3.00)
    assert states["TX"].max_price == pytest.approx(3.50)


@pytest.mark.django_db
def test_full_state_breakdown_sorted_cheapest_first():
    _make_station(1, "5.00", "WA")
    _make_station(2, "2.00", "TX")
    _make_station(3, "3.50", "OK")

    result = compute_full_state_breakdown()

    assert [s.state for s in result] == ["TX", "OK", "WA"]


# --- compute_full_brand_breakdown --------------------------------------------


@pytest.mark.django_db
def test_full_brand_breakdown_independent_bucket_sorted_last():
    # Independent/other has more stations than the recognized brand, but
    # should still appear last -- it's a catch-all, not a real network.
    _make_station(1, "3.00", "OK", name="RANDOM LOCAL STOP A")
    _make_station(2, "3.10", "OK", name="RANDOM LOCAL STOP B")
    _make_station(3, "3.20", "OK", name="RANDOM LOCAL STOP C")
    _make_station(4, "3.00", "OK", name="LOVES TRAVEL STOP")

    result = compute_full_brand_breakdown()

    assert result[-1].brand == OTHER_BRAND
    assert result[-1].count == 3
    assert result[0].brand == "Love's"


@pytest.mark.django_db
def test_full_brand_breakdown_min_max_per_brand():
    _make_station(1, "3.00", "OK", name="LOVES A")
    _make_station(2, "4.00", "OK", name="LOVES B")

    result = compute_full_brand_breakdown()
    loves = next(b for b in result if b.brand == "Love's")

    assert loves.min_price == pytest.approx(3.00)
    assert loves.max_price == pytest.approx(4.00)
    assert loves.avg_price == pytest.approx(3.50)
