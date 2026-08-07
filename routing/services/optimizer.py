"""Cost-optimal fuel stop planning: the classic "gas station" greedy, adapted
for off-corridor detours.

WHY this greedy is optimal: with a fixed tank range, the cheapest way to fuel
a trip is to always delay buying gas for as long as possible, buying only
enough to reach the next opportunity that is *at least as good*. Formally: at
any station you're standing at, if some reachable station ahead (within one
full tank) is cheaper, buying more than the minimum needed to reach it is
strictly wasteful — you'd be prepaying gallons you could buy cheaper very
soon. Conversely, if nothing ahead is cheaper, every gallon you might need
for the next full tank's worth of driving is best bought right now, at the
best price you'll see for a while — so fill up completely. This is a
textbook greedy-exchange argument: any schedule that deviates from these two
rules can be transformed into one that follows them without increasing cost.
(This part of the proof is exact for the classic, detour-free problem.)

Three refinements on top of the textbook version:
  1. A station reached by a detour is ranked by *effective* cost, not sticker
     price — see effective_cost() below for the blended-average-cost model
     used to estimate a detour's true cost. This is a well-reasoned
     approximation, not an exact optimum (see effective_cost's docstring for
     why a fully exact version would require lookahead/DP), but it strictly
     improves on pricing detour fuel at a flat, purchase-size-independent
     rate.
  2. The trip's finish line is treated as a free, always-available "target":
     once the destination is reachable on the current tank, we buy only the
     exact remainder needed and stop — never top off fuel that will never be
     used.
  3. The tank starts *empty*, not full. There's no fuel price defined at the
     origin itself, so the truck can't price-shop before its first fill: it
     fuels up at the nearest station to the origin (whatever that costs),
     then applies the same cheaper-ahead-or-fill-full rule from there onward.
     That first purchase is a real, charged stop — not a free starting tank.
"""

from __future__ import annotations

from dataclasses import dataclass

PRICE_EPSILON = 1e-9
DISTANCE_EPSILON = 1e-6


class NoReachableStationError(Exception):
    """No station (and not the destination either) is reachable within one tank
    of the current position — a genuine gap in fuel coverage along the route.
    """

    def __init__(self, position_miles: float, remaining_trip_miles: float, tank_range_miles: float):
        self.position_miles = position_miles
        self.remaining_trip_miles = remaining_trip_miles
        self.tank_range_miles = tank_range_miles
        super().__init__(
            f"No fuel station reachable within {tank_range_miles:.0f} miles of mile "
            f"{position_miles:.1f} ({remaining_trip_miles:.1f} miles remain to the "
            f"destination) — route has an unreachable fuel gap."
        )


@dataclass(frozen=True)
class StationCandidate:
    station_id: int
    name: str
    address: str
    city: str
    state: str
    price: float
    miles_from_start: float
    detour_miles: float
    latitude: float
    longitude: float


@dataclass(frozen=True)
class FuelStop:
    station_id: int
    name: str
    address: str
    city: str
    state: str
    price_per_gallon: float
    gallons: float
    cost: float
    miles_from_start: float
    detour_miles: float
    latitude: float
    longitude: float


@dataclass(frozen=True)
class OptimizerResult:
    total_distance_miles: float
    total_fuel_cost: float
    fuel_stops: list[FuelStop]


def effective_cost(price: float, detour_miles: float, tank_range_miles: float, outbound_reference_price: float) -> float:
    """Per-gallon cost of fueling at a station reached by a round-trip detour,
    including the detour's own fuel cost.

    A round trip off the highway and back burns fuel that never advances the
    trip. Gasoline is fungible once it's in the tank, so it isn't meaningful
    to ask "which price paid for the detour gallons" in general — but the two
    legs of the round trip *are* distinguishable by when they happen:
      - The outbound leg (route -> pump) burns whatever's already blended in
        the tank *before* this purchase — priced at `outbound_reference_price`
        (the running weighted-average cost of currently held fuel, or this
        station's own price if the tank is empty on arrival).
      - The return leg (pump -> route) burns fuel bought right here, priced
        at this station's own `price`.

    Both legs' cost is amortized over a full tank's capacity
    (tank_range_miles / mpg gallons) to get a per-gallon rate comparable to a
    plain sticker price. A full tank is used as the yardstick — not the exact
    amount that will be bought here — because that amount isn't known until
    *after* this comparison decides whether visiting is worth it at all; an
    exact treatment would need to look ahead at what's reachable beyond this
    station too (effectively turning the greedy into a small DP). mpg cancels
    out of the amortization entirely (detour gallons and tank-capacity
    gallons both scale by 1/mpg), leaving a pure mileage ratio:

        effective_cost = price + (detour_miles / tank_range_miles)
                                  * (outbound_reference_price + price)

    When there's no blending history yet (outbound_reference_price == price,
    e.g. the tank was just filled entirely from this same station), this
    collapses to price * (1 + 2*detour_miles/tank_range_miles) — pricing both
    legs of the round trip at the same rate, as expected when there's only
    one price in play.
    """
    detour_fraction = detour_miles / tank_range_miles
    return price + detour_fraction * (outbound_reference_price + price)


def _to_stop(station: StationCandidate, gallons: float, cost: float) -> FuelStop:
    return FuelStop(
        station_id=station.station_id,
        name=station.name,
        address=station.address,
        city=station.city,
        state=station.state,
        price_per_gallon=station.price,
        gallons=gallons,
        cost=cost,
        miles_from_start=station.miles_from_start,
        detour_miles=station.detour_miles,
        latitude=station.latitude,
        longitude=station.longitude,
    )


def plan_fuel_stops(
    total_distance_miles: float,
    candidates: list[StationCandidate],
    *,
    tank_range_miles: float,
    mpg: float,
) -> OptimizerResult:
    """Compute the cheapest sequence of fuel stops covering the trip.

    `candidates` are stations already matched to the route corridor (see
    corridor.py), each with a mile-marker and a one-way detour distance. The
    tank starts empty: the first fuel purchase happens at the station nearest
    the origin (that's reachable at all — see NoReachableStationError below),
    and every purchase after that follows the cheaper-ahead-or-fill-full rule,
    ranking detour stations by the blended-average-cost model in
    effective_cost() above.
    """
    if total_distance_miles <= DISTANCE_EPSILON:
        return OptimizerResult(total_distance_miles=total_distance_miles, total_fuel_cost=0.0, fuel_stops=[])

    sorted_candidates = sorted(candidates, key=lambda c: c.miles_from_start)

    start_reachable = [c for c in sorted_candidates if c.miles_from_start + 2 * c.detour_miles <= tank_range_miles + DISTANCE_EPSILON]
    if not start_reachable:
        raise NoReachableStationError(0.0, total_distance_miles, tank_range_miles)
    current_station: StationCandidate = start_reachable[0]  # nearest to the origin

    position = current_station.miles_from_start
    gallons_in_tank = 0.0
    avg_cost_in_tank = 0.0  # meaningless while gallons_in_tank == 0; never read in that case
    stops: list[FuelStop] = []
    total_cost = 0.0
    tank_capacity_gallons = tank_range_miles / mpg

    def buy(gallons: float, price: float) -> float:
        nonlocal gallons_in_tank, avg_cost_in_tank, total_cost
        if gallons <= DISTANCE_EPSILON:
            return 0.0
        cost = gallons * price
        total_cost += cost
        new_total = gallons_in_tank + gallons
        avg_cost_in_tank = (gallons_in_tank * avg_cost_in_tank + gallons * price) / new_total
        gallons_in_tank = new_total
        return cost

    while True:
        remaining_trip = total_distance_miles - position
        if remaining_trip <= gallons_in_tank * mpg + DISTANCE_EPSILON:
            break  # current fuel is enough to coast to the finish

        reachable = [
            c
            for c in sorted_candidates
            if c.miles_from_start > position + DISTANCE_EPSILON
            and (c.miles_from_start - position) + 2 * c.detour_miles <= tank_range_miles + DISTANCE_EPSILON
        ]
        can_finish_on_full_tank = remaining_trip <= tank_range_miles + DISTANCE_EPSILON

        if not reachable and not can_finish_on_full_tank:
            raise NoReachableStationError(position, remaining_trip, tank_range_miles)

        current_price = current_station.price
        outbound_reference_price = avg_cost_in_tank if gallons_in_tank > DISTANCE_EPSILON else current_price

        def eff(c: StationCandidate) -> float:
            return effective_cost(c.price, c.detour_miles, tank_range_miles, outbound_reference_price)

        cheaper_ahead = sorted(
            (c for c in reachable if eff(c) < current_price - PRICE_EPSILON),
            key=lambda c: c.miles_from_start,
        )

        if cheaper_ahead:
            target = cheaper_ahead[0]
            distance_needed = (target.miles_from_start - position) + 2 * target.detour_miles
            gallons_needed = distance_needed / mpg
            gallons_to_buy = max(0.0, gallons_needed - gallons_in_tank)

            cost = buy(gallons_to_buy, current_price)
            if cost:
                stops.append(_to_stop(current_station, gallons_to_buy, cost))

            gallons_in_tank -= gallons_needed
            position = target.miles_from_start
            current_station = target

        elif can_finish_on_full_tank:
            gallons_needed = remaining_trip / mpg
            gallons_to_buy = max(0.0, gallons_needed - gallons_in_tank)

            cost = buy(gallons_to_buy, current_price)
            if cost:
                stops.append(_to_stop(current_station, gallons_to_buy, cost))

            gallons_in_tank -= gallons_needed
            position = total_distance_miles
            break

        else:
            target = min(reachable, key=eff)
            gallons_to_buy = max(0.0, tank_capacity_gallons - gallons_in_tank)

            cost = buy(gallons_to_buy, current_price)
            if cost:
                stops.append(_to_stop(current_station, gallons_to_buy, cost))

            distance_to_target = (target.miles_from_start - position) + 2 * target.detour_miles
            gallons_in_tank -= distance_to_target / mpg
            position = target.miles_from_start
            current_station = target

    return OptimizerResult(total_distance_miles=total_distance_miles, total_fuel_cost=total_cost, fuel_stops=stops)
