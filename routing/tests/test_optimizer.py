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
        min_purchase_gallons=kwargs.get("min_purchase_gallons", 0.0),
    )


# --- effective_cost: pure formula ------------------------------------------


def test_effective_cost_with_zero_detour_equals_price():
    result = effective_cost(price=3.00, detour_miles=0.0, tank_range_miles=TANK_RANGE_MILES, outbound_reference_price=3.00)
    assert result == pytest.approx(3.00)


def test_effective_cost_amortizes_detour_toll_over_a_full_tank():
    # No blending history (outbound reference == this station's own price):
    # price + (detour/tank_range)*(price+price) = 3.00 + (5/500)*6.00 = 3.00 + 0.06 = 3.06
    result = effective_cost(price=3.00, detour_miles=5.0, tank_range_miles=TANK_RANGE_MILES, outbound_reference_price=3.00)
    assert result == pytest.approx(3.06)


def test_effective_cost_uses_blended_outbound_reference():
    # Outbound leg (route -> pump) burns fuel already in the tank, valued at
    # the blended reference price (3.40, e.g. from an earlier, pricier fill)
    # -- not this station's own (cheaper) price. Return leg uses this
    # station's own price (3.08).
    # 3.08 + (1.2/500)*(3.40+3.08) = 3.08 + 0.0024*6.48 = 3.08 + 0.015552
    result = effective_cost(price=3.08, detour_miles=1.2, tank_range_miles=TANK_RANGE_MILES, outbound_reference_price=3.40)
    assert result == pytest.approx(3.095552)


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
    # Cheaper sticker price but a huge detour (80mi one-way): even amortized
    # over a full 50gal tank, that's 160 of the 500 tank-range miles going
    # toward the round trip -- effective cost 2.50 + (80/500)*(2.00+2.50) = 3.22
    cheap_but_far = _station(1, 300, price=2.50, detour_miles=80.0, name="Cheap But Far")
    # Pricier sticker price, right on the corridor: effective cost stays 3.00
    pricier_but_close = _station(2, 350, price=3.00, detour_miles=0.0, name="Pricier But Close")

    result = _plan(700.0, [starter, cheap_but_far, pricier_but_close])

    assert result.fuel_stops[0].station_id == 3  # starter: nearest to the origin

    # Nothing beats the starter's $2.00 by effective cost, so it fills the
    # tank completely and drives to whichever reachable station is cheapest
    # by *effective* cost -- the pricier-but-close one, not the cheap-but-far
    # one, whose 80-mile detour outweighs its lower sticker price even once
    # amortized over a full tank.
    second = result.fuel_stops[1]
    assert second.station_id == 2
    assert second.price_per_gallon == pytest.approx(3.00)

    assert all(stop.station_id != 1 for stop in result.fuel_stops)


def test_small_detour_with_big_price_gap_is_worth_a_partial_buy():
    # The motivating regression case: a detour so small relative to the
    # sticker-price gap that it's clearly worth bridging to, even once the
    # naive (unamortized) formula would have said otherwise. Mirrors a real
    # observed case: $3.40/gal at mile 4 (10mi detour) vs $3.08/gal at mile
    # 61 (1.2mi detour) -- the 1.2mi detour barely matters amortized over a
    # full tank, so pump2 should win and only a partial buy happens at pump1.
    pump1 = _station(1, 4, price=3.40, detour_miles=10.0, name="Pump 1")
    pump2 = _station(2, 61, price=3.08, detour_miles=1.2, name="Pump 2")

    result = _plan(400.0, [pump1, pump2])

    assert len(result.fuel_stops) == 2
    first, second = result.fuel_stops

    assert first.station_id == 1
    # Bridge to pump2: (61-4) + 2*1.2 = 59.4mi = 5.94gal -- NOT a full tank.
    assert first.gallons == pytest.approx(5.94)
    assert first.cost == pytest.approx(5.94 * 3.40)

    assert second.station_id == 2
    assert second.gallons == pytest.approx(33.9)
    assert second.cost == pytest.approx(33.9 * 3.08)

    total = result.total_fuel_cost
    assert total == pytest.approx(5.94 * 3.40 + 33.9 * 3.08)

    # Sanity check against the old (wrong) behavior: filling the tank
    # completely at pump1 and coasting past pump2 would have cost more.
    fill_full_at_pump1_cost = (TANK_RANGE_MILES / MPG) * 3.40
    assert total < fill_full_at_pump1_cost


def test_full_tank_amortization_is_a_known_approximation():
    # Documents a known limitation of amortizing a detour's toll over a full
    # tank's capacity rather than the amount actually bought: when a
    # candidate's real, small purchase can't absorb the toll as cheaply as a
    # full tank would, the model can still prefer a detour that a true
    # total-cost comparison would reject. This is an accepted, documented
    # tradeoff (see effective_cost()'s docstring), not a bug -- this test
    # pins the current, known-approximate behavior so a future change to the
    # model is a conscious decision, not an accidental regression.
    cheap_start = _station(1, 100, price=2.00, name="Cheap Start")
    pricier_next = _station(2, 520, price=2.50, name="Pricier Next")
    # Only slightly cheaper than pricier_next, and reachable with a 25mi
    # detour -- attractive when its toll is amortized over a full tank, even
    # though only a few gallons end up being bought nearby.
    marginal_detour = _station(3, 620, price=2.28, detour_miles=25.0, name="Marginal Detour")

    result = _plan(650.0, [cheap_start, pricier_next, marginal_detour])

    # The model chooses to visit the detour station...
    assert [stop.station_id for stop in result.fuel_stops] == [1, 2, 3]
    # ...even though skipping it and buying the rest at pricier_next is
    # actually cheaper in total -- the known approximation error.
    skip_detour_cost = (TANK_RANGE_MILES / MPG) * 2.00 + 5.0 * 2.50
    assert result.total_fuel_cost > skip_detour_cost


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


# --- min_purchase_gallons: don't hop stop-to-stop for a splash of fuel -----


def test_without_min_purchase_gallons_the_tiny_bridge_is_taken():
    # Baseline (no minimum): the optimizer takes every marginally cheaper
    # station it finds, however little fuel that means buying at the one
    # before it -- the exact behavior min_purchase_gallons exists to curb.
    station_a = _station(1, 4, price=3.40, name="A")
    station_b = _station(2, 6, price=3.35, name="B")  # 2mi away: 0.2gal bridge
    station_c = _station(3, 150, price=3.00, name="C")

    result = _plan(150.0, [station_a, station_b, station_c])

    assert len(result.fuel_stops) == 2
    assert result.fuel_stops[0].station_id == 1
    assert result.fuel_stops[0].gallons == pytest.approx(0.2)
    assert result.fuel_stops[1].station_id == 2
    assert result.fuel_stops[1].gallons == pytest.approx(14.4)


def test_min_purchase_gallons_skips_a_station_too_close_to_be_worth_stopping():
    # Same layout, but with a 10gal minimum: bridging to B would only need
    # 0.2gal, so B is skipped entirely in favor of C (146mi away, 14.6gal --
    # a real fill), bought directly from A.
    station_a = _station(1, 4, price=3.40, name="A")
    station_b = _station(2, 6, price=3.35, name="B")
    station_c = _station(3, 150, price=3.00, name="C")

    result = _plan(150.0, [station_a, station_b, station_c], min_purchase_gallons=10.0)

    assert len(result.fuel_stops) == 1
    stop = result.fuel_stops[0]
    assert stop.station_id == 1
    assert stop.gallons == pytest.approx(14.6)
    assert stop.cost == pytest.approx(14.6 * 3.40)


def test_min_purchase_gallons_never_skips_a_free_coast_to_a_cheaper_station():
    # If there's already enough fuel in the tank to coast to a cheaper
    # station for free, that's not "a stop" being made too small -- no
    # purchase happens there at all, so the minimum never blocks the switch.
    station_a = _station(1, 100, price=3.50, name="A")  # start: fills a full tank
    station_x = _station(2, 160, price=3.55, name="X")  # 60mi away: the fill-full target
    station_y = _station(3, 170, price=3.40, name="Y")  # 10mi past X, cheaper, reached for free

    result = _plan(650.0, [station_a, station_x, station_y], min_purchase_gallons=10.0)

    # X is passed through with a full tank's worth of leftover fuel -- no
    # purchase happens there, so it never appears as a stop.
    assert [stop.station_id for stop in result.fuel_stops] == [1, 3]

    assert result.fuel_stops[0].gallons == pytest.approx(TANK_RANGE_MILES / MPG)
    assert result.fuel_stops[0].cost == pytest.approx((TANK_RANGE_MILES / MPG) * 3.50)

    # Finishes the trip from Y, at Y's (cheaper) price -- proving the free
    # coast from X to Y actually happened.
    assert result.fuel_stops[1].gallons == pytest.approx(5.0)
    assert result.fuel_stops[1].price_per_gallon == pytest.approx(3.40)


def test_no_stations_at_all_raises_even_for_a_short_trip():
    # Tank starts empty -- with nowhere to fuel up, even a short trip can't
    # be completed, so this must fail loudly rather than silently reporting
    # a free $0 trip.
    with pytest.raises(NoReachableStationError) as exc_info:
        _plan(300.0, [])

    assert exc_info.value.position_miles == pytest.approx(0.0)
