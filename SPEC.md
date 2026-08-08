# Fuel Route Optimizer — Assessment Project

## Goal
Django API: given start/finish in the USA, return the driving route, cost-optimal
fuel stops (500-mile tank range), and total fuel cost at 10 mpg, using prices
from data/fuel-prices-for-be-assessment.csv (8,151 rows, ~6,700 unique stations,
columns: OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID,
Retail Price). Addresses are highway-exit style with NO coordinates.

## Stack (locked decisions — do not change)
- Django 5.2 (latest stable) + Django REST Framework, Python 3.12
- PostgreSQL (docker-compose locally; Neon in production), psycopg
- numpy + scipy (cKDTree) for spatial work, `polyline` lib for OSRM geometry
- OSRM public server (router.project-osrm.org) for routing — NO API key
- Nominatim for geocoding user place-name input only — cached permanently
- Docker + docker-compose; deploy target: Render free web service + Neon
- Frontend: ONE Django template at "/", vanilla JS + Leaflet, calling our own API

## Architecture rules
- Geocoding of the 6,700 stations happens OFFLINE in a management command
  (`load_fuel_data`) at CITY+STATE level using an offline US-cities dataset
  (e.g. the `simplemaps`-style bundled CSV or `uszipcode`). ZERO external calls.
  Failed matches fall back to state centroid and are logged, never dropped.
- The command is an IDEMPOTENT UPSERT keyed on OPIS ID: new station -> insert,
  existing -> update price only. Dedupe input keeping cheapest price per OPIS ID.
- Model split: FuelStation holds static identity + coords + current_price.
  PriceHistory(station, price, effective_at) appends on every change.
- At startup (AppConfig.ready), load stations into a NumPy coord array + build
  scipy cKDTree ONCE. Prices live in a separate aligned NumPy array swapped
  atomically on updates. A `price_version` int bumps on every price change.
- Request path: max 1 external call with coord input (OSRM), max 3 with names
  (2 Nominatim + OSRM). Geocode results cached forever (DB-backed). Full route
  responses cached with price_version inside the cache key.
- Corridor matching: decode OSRM polyline, cumulative haversine miles
  (vectorized), downsample to ~1 point per 2 miles, single batched
  cKDTree.query (workers=-1) in equirectangular-projected space
  (lng scaled by cos(lat)), 10-mile detour radius (settings-configurable).
- Optimizer: greedy for the gas-station problem (provably optimal for the
  classic detour-free version): at each station, if a CHEAPER station is
  within remaining 500-mile range, buy only enough fuel to reach it;
  otherwise FILL FULL and drive to the cheapest station in range. Tank
  starts EMPTY: the first purchase happens at the CHEAPEST (effective-cost)
  station reachable within a short START_SEARCH_RADIUS_MILES (default 15mi,
  settings-configurable) of mile 0, not the nearest — the origin-to-entry
  leg is unpriced for every station within that radius equally, so entering
  at a nearer-but-pricier one would force a real, avoidable purchase to
  bridge to the cheaper one just past it. If nothing is within that radius,
  the search falls back to one full tank of mile 0 (422 if even that finds
  nothing) rather than stranding the truck. The same cheaper-ahead rule
  applies from there on, over the full tank range. Rank detour stations by EFFECTIVE
  cost: price + (detour_miles / tank_range_miles) * (blended_avg_cost_in_tank
  + price) — the round trip's outbound leg burns whatever's already blended
  in the tank (weighted-average cost of held fuel), the return leg burns
  fuel bought at that station's own price, both amortized over a full
  tank's capacity. This is a documented approximation (assumes a near-full
  purchase there), not an exact optimum — see README's "known limitation"
  note and `test_full_tank_amortization_is_a_known_approximation`.
- Fuel cost = sum(gallons bought at each stop * that stop's price), 10 mpg.
  Every trip with positive distance buys real fuel and gets >=1 stop; only a
  zero-distance trip (start == finish) needs none.
- MIN_PURCHASE_GALLONS (default 10, settings-configurable): a reachable
  station only counts as "cheaper ahead" if bridging to it means buying at
  least this many gallons here; otherwise skip it and try the next
  reachable-and-cheaper one, falling through to fill-full/finish-here if
  none qualify. Prevents hopping between densely-packed near-city stations
  for a fraction of a gallon each. Exception: a free coast (0 gallons needed
  to reach a cheaper station, already covered by fuel in tank) is never
  blocked, since no purchase happens there at all.

## API contract
POST /api/route/  body: {"start": "...", "finish": "..."} — each value is
either "City, ST" or "lat,lng". Response:
{ total_distance_miles, total_fuel_cost, fuel_stops: [{name, address, city,
  state, price_per_gallon, gallons, cost, miles_from_start, detour_miles}],
  route: <GeoJSON LineString>, cached: bool, price_version }
Errors: 400 bad input, 404 location not found, 422 no reachable station in a
500-mile stretch (clear message).

## Style rules
- Type hints everywhere, small pure functions in routing/services/, docstrings
  explaining WHY on the optimizer.
- Tests with pytest-django for: dedupe, upsert idempotency, corridor matcher,
  and optimizer edge cases (cheaper-ahead, fill-full, gap > 500 mi, short trip).
  Optimizer tests use synthetic stations, no network. Mock OSRM/Nominatim.
- UI: match reference/ mockup — utilitarian logistics look, near-white bg,
  thin 1px borders, ONE dark green accent, no gradients, no emoji, no shadows,
  tabular figures for prices. Hand-written CSS, no frameworks.
- README must document: setup, API docs with curl examples, the optimality
  argument for the greedy algorithm, the price-update design, assumptions.