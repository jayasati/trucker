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


# --- zero-distance trip: nothing to buy --------------------------------------


def test_zero_distance_trip_needs_no_fuel():
    result = _plan(0.0, [_station(1, 100, price=3.00)])
    assert result.fuel_stops == []
    assert result.total_fuel_cost == 0.0


# --- tank starts empty: the first purchase happens at the nearest station ---


def test_trip_within_one_tank_still_buys_fuel_at_nearest_station():
    # Tank starts empty, so even a trip that fits in one tank needs a real
    # fill-up: the truck tops off at the nearest station on the way, buying
    # cheaper fuel further on when a cheaper station becomes reachable.
    candidates = [_station(1, 100, price=3.00), _station(2, 250, price=2.80)]

    result = _plan(300.0, candidates)

    assert len(result.fuel_stops) == 2
    first, second = result.fuel_stops
    assert first.station_id == 1
    # Needed 150mi = 15gal to reach the cheaper station; had none in tank.
    assert first.gallons == pytest.approx(15.0)
    assert first.cost == pytest.approx(15.0 * 3.00)

    assert second.station_id == 2
    # Remaining 50mi = 5gal to finish.
    assert second.gallons == pytest.approx(5.0)
    assert second.cost == pytest.approx(5.0 * 2.80)

    assert result.total_fuel_cost == pytest.approx(15.0 * 3.00 + 5.0 * 2.80)


def test_trip_covered_entirely_by_the_nearest_station():
    # A single station, well within tank range of the origin: the whole trip
    # is bought there since nothing cheaper is ever reachable.
    result = _plan(TANK_RANGE_MILES, [_station(1, 250, price=3.00)])

    assert len(result.fuel_stops) == 1
    stop = result.fuel_stops[0]
    assert stop.station_id == 1
    # Station is at mile 250, so only the remaining 250mi (25gal) is bought.
    assert stop.gallons == pytest.approx(25.0)
    assert stop.cost == pytest.approx(25.0 * 3.00)


# --- cheaper station ahead: buy only enough to reach it ---------------------


def test_cheaper_station_ahead_triggers_partial_buy():
    # Station1 is the only station reachable from the origin (within 500mi),
    # so it's the forced first stop, arriving with an empty tank.
    station1 = _station(1, 480, price=4.00)
    # Station2 is cheaper and reachable from station1 (120mi away); the truck
    # should buy just enough at station1 to bridge the 120mi gap, not fill up.
    station2 = _station(2, 600, price=3.00)

    result = _plan(650.0, [station1, station2])

    assert len(result.fuel_stops) == 2

    first = result.fuel_stops[0]
    assert first.station_id == 1
    # Needed 120mi = 12gal; started this leg with an empty tank.
    assert first.gallons == pytest.approx(12.0)
    assert first.cost == pytest.approx(12.0 * 4.00)

    second = result.fuel_stops[1]
    assert second.station_id == 2
    # Arrives at station2 empty; needs the final 50mi = 5gal to finish.
    assert second.gallons == pytest.approx(5.0)
    assert second.cost == pytest.approx(5.0 * 3.00)

    assert result.total_fuel_cost == pytest.approx(12.0 * 4.00 + 5.0 * 3.00)


# --- nothing cheaper ahead: fill the tank completely -------------------------


def test_fill_full_when_nothing_cheaper_in_range():
    # Station1 (nearest, forced first stop) then Station2 further away and
    # *more* expensive -- no reason to buy less than a full tank at station1
    # since nothing better is coming up within range.
    station1 = _station(1, 100, price=3.00)
    station2 = _station(2, 550, price=3.50)

    result = _plan(1000.0, [station1, station2])

    first = result.fuel_stops[0]
    assert first.station_id == 1
    # Arrived empty and filled up completely.
    assert first.gallons == pytest.approx(TANK_RANGE_MILES / MPG)
    assert first.cost == pytest.approx((TANK_RANGE_MILES / MPG) * 3.00)

    assert result.fuel_stops[1].station_id == 2


# --- detour penalty flips which station is chosen ---------------------------


def test_detour_penalty_flips_choice_between_two_stations():
    # A cheap "starter" station right near the origin -- unambiguously the
    # nearest, so it's the forced first fill regardless of price elsewhere.
    starter = _station(3, 50, price=2.00, name="Starter")
    # Cheaper sticker price but a big detour: effective cost 2.50 + (2*8/10)*2.50 = 6.50
    cheap_but_far = _station(1, 300, price=2.50, detour_miles=8.0, name="Cheap But Far")
    # Pricier sticker price, right on the corridor: effective cost stays 3.00
    pricier_but_close = _station(2, 350, price=3.00, detour_miles=0.0, name="Pricier But Close")

    assert effective_cost(2.50, 8.0, MPG) > effective_cost(3.00, 0.0, MPG)

    result = _plan(700.0, [starter, cheap_but_far, pricier_but_close])

    assert result.fuel_stops[0].station_id == 3  # starter: nearest to the origin

    # Nothing beats the starter's $2.00 by effective cost, so it fills the
    # tank completely and drives to whichever reachable station is cheapest
    # by *effective* cost -- the pricier-but-close one, not the cheap-but-far
    # one, despite its lower sticker price.
    second = result.fuel_stops[1]
    assert second.station_id == 2
    assert second.price_per_gallon == pytest.approx(3.00)

    assert all(stop.station_id != 1 for stop in result.fuel_stops)


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
    # Sole station is beyond the first tank's reach from the origin.
    result_candidates = [_station(1, 550, price=3.00)]

    with pytest.raises(NoReachableStationError) as exc_info:
        _plan(600.0, result_candidates)

    assert exc_info.value.position_miles == pytest.approx(0.0)


def test_no_stations_at_all_raises_when_trip_exceeds_tank_range():
    with pytest.raises(NoReachableStationError):
        _plan(600.0, [])


def test_no_stations_at_all_raises_even_for_a_short_trip():
    # Tank starts empty -- with nowhere to fuel up, even a short trip can't
    # be completed, so this must fail loudly rather than silently reporting
    # a free $0 trip.
    with pytest.raises(NoReachableStationError) as exc_info:
        _plan(300.0, [])

    assert exc_info.value.position_miles == pytest.approx(0.0)
