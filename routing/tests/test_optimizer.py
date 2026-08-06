import pytest

from routing.services.optimizer import (
    NoReachableStationError,
    StationCandidate,
    effective_cost,
    plan_fuel_stops,
)

TANK_RANGE_MILES = 500.0
MPG = 10.0


def _station(station_id, miles_from_start, price, detour_miles=0.0, name=None):
    return StationCandidate(
        station_id=station_id,
        name=name or f"Station {station_id}",
        address="123 Highway",
        city="Somewhere",
        state="OK",
        price=price,
        miles_from_start=miles_from_start,
        detour_miles=detour_miles,
        latitude=36.0,
        longitude=-97.0,
    )


def _plan(total_distance_miles, candidates, **kwargs):
    return plan_fuel_stops(
        total_distance_miles,
        candidates,
        tank_range_miles=kwargs.get("tank_range_miles", TANK_RANGE_MILES),
        mpg=kwargs.get("mpg", MPG),
    )


# --- effective_cost: pure formula ------------------------------------------


def test_effective_cost_with_zero_detour_equals_price():
    assert effective_cost(price=3.00, detour_miles=0.0, mpg=MPG) == pytest.approx(3.00)


def test_effective_cost_adds_round_trip_detour_penalty():
    # price + (2*detour/mpg)*price = 3.00 + (2*5/10)*3.00 = 3.00 + 3.00 = 6.00
    assert effective_cost(price=3.00, detour_miles=5.0, mpg=MPG) == pytest.approx(6.00)


# --- trip shorter than the tank range ---------------------------------------


def test_short_trip_needs_no_stops_but_reports_estimated_cost():
    candidates = [_station(1, 100, price=3.00), _station(2, 250, price=2.80)]

    result = _plan(300.0, candidates)

    assert result.fuel_stops == []
    assert result.total_fuel_cost == 0.0
    # Estimated at the cheapest corridor price: 300mi / 10mpg * $2.80
    assert result.estimated_trip_cost == pytest.approx(30 * 2.80)


def test_short_trip_with_no_candidates_has_no_estimated_cost():
    result = _plan(300.0, [])

    assert result.fuel_stops == []
    assert result.total_fuel_cost == 0.0
    assert result.estimated_trip_cost is None


def test_short_trip_boundary_exactly_at_tank_range_needs_no_stops():
    result = _plan(TANK_RANGE_MILES, [_station(1, 250, price=3.00)])
    assert result.fuel_stops == []


# --- cheaper station ahead: buy only enough to reach it ---------------------


def test_cheaper_station_ahead_triggers_partial_buy():
    # Station1 is the only station reachable from the origin (within 500mi),
    # so it's the forced first stop, arriving with 20mi (2gal) left in the tank.
    station1 = _station(1, 480, price=4.00)
    # Station2 is cheaper and reachable from station1 (120mi away); the truck
    # should buy just enough at station1 to bridge the 120mi gap, not fill up.
    station2 = _station(2, 600, price=3.00)

    result = _plan(650.0, [station1, station2])

    assert len(result.fuel_stops) == 2

    first = result.fuel_stops[0]
    assert first.station_id == 1
    # Needed 120mi = 12gal; already had 20mi = 2gal in tank -> buy 10gal.
    assert first.gallons == pytest.approx(10.0)
    assert first.cost == pytest.approx(10.0 * 4.00)

    second = result.fuel_stops[1]
    assert second.station_id == 2
    # Arrives at station2 empty; needs the final 50mi = 5gal to finish.
    assert second.gallons == pytest.approx(5.0)
    assert second.cost == pytest.approx(5.0 * 3.00)

    assert result.total_fuel_cost == pytest.approx(10.0 * 4.00 + 5.0 * 3.00)


# --- nothing cheaper ahead: fill the tank completely -------------------------


def test_fill_full_when_nothing_cheaper_in_range():
    # Station1 (cheapest overall, forced first stop) then Station2 further
    # away and *more* expensive -- no reason to buy less than a full tank
    # at station1 since nothing better is coming up within range.
    station1 = _station(1, 100, price=3.00)
    station2 = _station(2, 550, price=3.50)

    result = _plan(1000.0, [station1, station2])

    first = result.fuel_stops[0]
    assert first.station_id == 1
    # Had 400mi (40gal) left on arrival; topped up to a full tank (50gal) -> bought 10gal.
    assert first.gallons == pytest.approx(10.0)
    assert first.cost == pytest.approx(10.0 * 3.00)

    # Departed station1 with a completely full tank (50 gallons of range).
    gallons_at_departure = 40.0 + first.gallons
    assert gallons_at_departure == pytest.approx(TANK_RANGE_MILES / MPG)

    assert result.fuel_stops[1].station_id == 2


# --- gap between stations exceeds tank range: must fail clearly -------------


def test_gap_exceeding_tank_range_raises_clear_error():
    station1 = _station(1, 100, price=3.00)
    station2 = _station(2, 700, price=2.50)  # 600mi from station1: unreachable on one tank

    with pytest.raises(NoReachableStationError) as exc_info:
        _plan(1200.0, [station1, station2])

    err = exc_info.value
    assert err.position_miles == pytest.approx(100.0)
    assert err.tank_range_miles == pytest.approx(TANK_RANGE_MILES)
    assert "500" in str(err)


def test_gap_at_trip_start_raises_when_nothing_reachable_at_all():
    # Sole station is beyond the first tank's reach, and the destination is too.
    result_candidates = [_station(1, 550, price=3.00)]

    with pytest.raises(NoReachableStationError) as exc_info:
        _plan(600.0, result_candidates)

    assert exc_info.value.position_miles == pytest.approx(0.0)


def test_no_stations_at_all_raises_when_trip_exceeds_tank_range():
    with pytest.raises(NoReachableStationError):
        _plan(600.0, [])


# --- detour penalty flips which station is chosen ---------------------------


def test_detour_penalty_flips_choice_between_two_stations():
    # Cheaper sticker price but a big detour: effective cost 2.50 + (2*8/10)*2.50 = 6.50
    cheap_but_far = _station(1, 300, price=2.50, detour_miles=8.0, name="Cheap But Far")
    # Pricier sticker price, right on the corridor: effective cost stays 3.00
    pricier_but_close = _station(2, 350, price=3.00, detour_miles=0.0, name="Pricier But Close")

    assert effective_cost(2.50, 8.0, MPG) > effective_cost(3.00, 0.0, MPG)

    result = _plan(700.0, [cheap_but_far, pricier_but_close])

    first_stop = result.fuel_stops[0]
    assert first_stop.station_id == 2  # picked despite the higher sticker price
    assert first_stop.price_per_gallon == pytest.approx(3.00)
