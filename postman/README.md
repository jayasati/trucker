# Postman collection

API tests for `POST /api/route/` and `GET /api/places/` — happy paths, caching, error cases
(`400`/`404`), and the business-logic invariants the optimizer guarantees:

- `fuel_stops` is a subset of `all_stops`, in mile order
- every pass-through waypoint bought `0` gallons and cost `0`
- **the tank ledger balances at every stop**: `tank_gallons_arriving + gallons == tank_gallons_departing`
- the tank never exceeds `TANK_RANGE_MILES / MPG` capacity anywhere on the route
- the first fuel stop is within the start-search radius, not just any reachable station
- a repeated identical request is served from cache (`cached: true`, near-zero `compute_ms`)

See [`README.md`](../README.md#the-optimizer-and-why-its-optimal) for the reasoning behind each
of these.

## Files

| File | Purpose |
|---|---|
| `Trucker.postman_collection.json` | The requests + test scripts |
| `Trucker.Local.postman_environment.json` | `baseUrl = http://localhost:8000` |
| `Trucker.Production.postman_environment.json` | `baseUrl` = the live Cloud Run demo |

## Running it

**In the Postman app:** File → Import → select all three files, pick an environment in the
top-right dropdown, then Runner → select the collection → Run.

**Headless (CI-friendly), via [Newman](https://www.npmjs.com/package/newman):**

```bash
npx newman run postman/Trucker.postman_collection.json \
  -e postman/Trucker.Production.postman_environment.json
```

Swap in `Trucker.Local.postman_environment.json` (after `docker compose up`) to test against a
local server instead.

## Notes

- Run "Plan route — short trip" before "Plan route — repeat request (cache hit)" (same
  start/finish) so there's something in the response cache to hit — the Postman Runner executes
  requests top-to-bottom within a folder, so this is already the default order.
- The `422` (unreachable fuel gap) and `502` (upstream routing/geocoding failure) error cases
  aren't included as live requests: `422` depends on the exact station dataset having a real
  coverage gap, and `502` depends on the public OSRM/Nominatim servers actually being down —
  neither is reliably reproducible on demand. Both are covered by `routing/tests/test_optimizer.py`
  and `routing/tests/` against synthetic data instead; see the `Errors` table in the main README
  for the shape of each response.
