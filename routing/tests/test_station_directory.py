import pytest

from routing.models import FuelStation
from routing.services.station_directory import filter_stations


def _make_station(opis_id, price, state, city="Anytown", name="TEST STOP"):
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


@pytest.mark.django_db
def test_filter_by_query_matches_name_or_city():
    _make_station(1, "3.00", "OK", city="Tulsa", name="LOVES TRAVEL STOP")
    _make_station(2, "3.00", "OK", city="Norman", name="PILOT")
    _make_station(3, "3.00", "OK", city="Lawton", name="RANDOM STOP")

    result = filter_stations(FuelStation.objects.all(), query="loves")
    assert [s.name for s in result] == ["LOVES TRAVEL STOP"]

    result = filter_stations(FuelStation.objects.all(), query="tulsa")
    assert [s.name for s in result] == ["LOVES TRAVEL STOP"]


@pytest.mark.django_db
def test_filter_by_state_is_case_insensitive():
    _make_station(1, "3.00", "OK")
    _make_station(2, "3.00", "TX")

    result = filter_stations(FuelStation.objects.all(), state="ok")
    assert [s.state for s in result] == ["OK"]


@pytest.mark.django_db
def test_filter_by_price_range():
    _make_station(1, "2.50", "OK")
    _make_station(2, "3.50", "OK")
    _make_station(3, "4.50", "OK")

    result = filter_stations(FuelStation.objects.all(), min_price="3.00", max_price="4.00")
    assert [float(s.current_price) for s in result] == [3.50]


@pytest.mark.django_db
def test_filter_ignores_invalid_price_input():
    _make_station(1, "3.00", "OK")

    result = filter_stations(FuelStation.objects.all(), min_price="not-a-number")
    assert result.count() == 1


@pytest.mark.django_db
def test_sort_price_desc():
    _make_station(1, "2.00", "OK", name="CHEAP")
    _make_station(2, "5.00", "OK", name="EXPENSIVE")

    result = filter_stations(FuelStation.objects.all(), sort="price_desc")
    assert [s.name for s in result] == ["EXPENSIVE", "CHEAP"]


@pytest.mark.django_db
def test_sort_by_name():
    _make_station(1, "3.00", "OK", name="ZEBRA STOP")
    _make_station(2, "3.00", "OK", name="ALPHA STOP")

    result = filter_stations(FuelStation.objects.all(), sort="name")
    assert [s.name for s in result] == ["ALPHA STOP", "ZEBRA STOP"]


@pytest.mark.django_db
def test_unknown_sort_falls_back_to_default():
    _make_station(1, "5.00", "OK", name="EXPENSIVE")
    _make_station(2, "2.00", "OK", name="CHEAP")

    result = filter_stations(FuelStation.objects.all(), sort="nonsense")
    assert [s.name for s in result] == ["CHEAP", "EXPENSIVE"]


@pytest.mark.django_db
def test_combined_filters():
    _make_station(1, "3.00", "OK", city="Tulsa", name="LOVES")
    _make_station(2, "9.00", "OK", city="Tulsa", name="LOVES EXPENSIVE")
    _make_station(3, "3.00", "TX", city="Tulsa", name="LOVES WRONG STATE")

    result = filter_stations(FuelStation.objects.all(), query="loves", state="OK", max_price="5.00")
    assert [s.name for s in result] == ["LOVES"]
