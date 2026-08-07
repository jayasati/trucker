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

Two refinements on top of the textbook version:
  1. Stations are ranked by *effective* cost (price inflated by the fuel
     burned on the round-trip detour off the highway), not sticker price, so
     a cheap-but-far station can correctly lose to a pricier-but-closer one.
  2. The trip's finish line is treated as a free, always-available "target":
     once the destination is reachable on the current tank, we buy only the
     exact remainder needed and stop — never top off fuel that will never be
     used.
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
    estimated_trip_cost: float | None


def effective_cost(price: float, detour_miles: float, mpg: float) -> float:
    """Price inflated by the cost of the fuel burned detouring off the highway
    and back (round trip), per SPEC.md: price + 2*detour_miles/mpg * price.
    """
    return price + (2.0 * detour_miles / mpg) * price


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
    corridor.py), each with a mile-marker and a one-way detour distance.
    """
    if total_distance_miles <= tank_range_miles + DISTANCE_EPSILON:
        cheapest = min(candidates, key=lambda c: effective_cost(c.price, c.detour_miles, mpg), default=None)
        estimated_trip_cost = (total_distance_miles / mpg) * cheapest.price if cheapest else None
        return OptimizerResult(
            total_distance_miles=total_distance_miles,
            total_fuel_cost=0.0,
            fuel_stops=[],
            estimated_trip_cost=estimated_trip_cost,
        )

    sorted_candidates = sorted(candidates, key=lambda c: c.miles_from_start)

    position = 0.0
    range_remaining = tank_range_miles
    current_station: StationCandidate | None = None
    stops: list[FuelStop] = []
    total_cost = 0.0

    while True:
        remaining_trip = total_distance_miles - position
        if remaining_trip <= range_remaining + DISTANCE_EPSILON:
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

        current_price = current_station.price if current_station is not None else None
        cheaper_ahead = []
        if current_price is not None:
            cheaper_ahead = sorted(
                (c for c in reachable if effective_cost(c.price, c.detour_miles, mpg) < current_price - PRICE_EPSILON),
                key=lambda c: c.miles_from_start,
            )

        if cheaper_ahead:
            target = cheaper_ahead[0]
            distance_needed = (target.miles_from_start - position) + 2 * target.detour_miles
            gallons_needed = distance_needed / mpg
            gallons_have = range_remaining / mpg
            gallons_to_buy = max(0.0, gallons_needed - gallons_have)

            if gallons_to_buy > DISTANCE_EPSILON and current_station is not None:
                cost = gallons_to_buy * current_station.price
                total_cost += cost
                stops.append(_to_stop(current_station, gallons_to_buy, cost))

            range_remaining = range_remaining + gallons_to_buy * mpg - distance_needed
            position = target.miles_from_start
            current_station = target

        elif can_finish_on_full_tank:
            gallons_needed = remaining_trip / mpg
            gallons_have = range_remaining / mpg
            gallons_to_buy = max(0.0, gallons_needed - gallons_have)

            if gallons_to_buy > DISTANCE_EPSILON and current_station is not None:
                cost = gallons_to_buy * current_station.price
                total_cost += cost
                stops.append(_to_stop(current_station, gallons_to_buy, cost))

            position = total_distance_miles
            range_remaining = range_remaining + gallons_to_buy * mpg - remaining_trip
            break

        else:
            target = min(reachable, key=lambda c: effective_cost(c.price, c.detour_miles, mpg))
            gallons_to_buy = max(0.0, (tank_range_miles - range_remaining) / mpg)

            if gallons_to_buy > DISTANCE_EPSILON and current_station is not None:
                cost = gallons_to_buy * current_station.price
                total_cost += cost
                stops.append(_to_stop(current_station, gallons_to_buy, cost))

            distance_to_target = (target.miles_from_start - position) + 2 * target.detour_miles
            range_remaining = range_remaining + gallons_to_buy * mpg - distance_to_target
            position = target.miles_from_start
            current_station = target

    return OptimizerResult(
        total_distance_miles=total_distance_miles,
        total_fuel_cost=total_cost,
        fuel_stops=stops,
        estimated_trip_cost=None,
    )
