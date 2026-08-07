# Trucker — Demo Script
*Target length: ~6–8 minutes. Live URL: https://trucker-319172055462.us-east4.run.app*

---

## 1. Hook (30 sec)

> "Say you're dispatching a truck from Milwaukee to Miami. It's got a 500-mile tank range at
> 10 miles per gallon, and there are thousands of truck stops along the way, all charging
> different prices. Where do you stop, and how much do you fill up, so the total fuel bill is
> as low as possible?
>
> That's what this app solves — Trucker. Give it a start and a finish, and it returns the
> driving route, the cheapest set of fuel stops, and the total cost, computed against a real
> dataset of 6,738 truck stops."

---

## 2. Live demo — Route Planner (`/`) (2–3 min)

**Action:** Open the homepage. Type a short trip first, then a long one.

1. **Short trip** — e.g. `Milwaukee, WI` → `Madison, WI`
   - Talking point: "Under the 500-mile tank range, but the tank starts empty — like a real
     truck leaving the yard — so it still buys real fuel at the nearest station and shows a
     real cost, not a placeholder."
   - Point out the autocomplete on the city fields — "That's fully offline, backed by a
     bundled ZIP-code dataset, not a live API call."

2. **Long trip** — e.g. `Milwaukee, WI` → `Miami, FL`
   - Watch the map draw the route and drop pins at each recommended fuel stop.
   - Talking point: "Each stop shows exactly how many gallons to buy, the price, and the
     total cost at that stop — not just 'fill up here,' but the *optimal* amount to buy."
   - Click a stop pin to show the price/gallons/detour detail.

**Talking point (optimizer):**
> "The rule behind this is simple but provably optimal: at any point, if a cheaper station is
> reachable within one tank, buy only enough fuel to get there. Otherwise, fill up completely
> and drive to the cheapest station in range. It's a textbook greedy-exchange argument — buying
> more than necessary before a cheaper option is always wasteful, and if nothing cheaper is
> ahead, now is the best time to buy a full tank."

*(Optional, if audience is technical: mention the effective-cost formula — `price + (2 × detour
miles / mpg) × price` — so a cheap-but-far station can lose to a pricier-but-closer one.)*

---

## 3. Live demo — supporting pages (1.5–2 min)

**`/fuel/` — Fuel Directory**
> "Every one of the 6,738 stations is searchable and filterable here — by state, brand,
> price range."
- Demo a filter or search.

**`/dashboard/` — Fleet-wide aggregates**
> "This rolls the whole dataset up into avg/min/max pricing, geocode precision, and top
> networks — the kind of at-a-glance view a fleet manager would want."

**`/analytics/` — State/brand breakdown**
> "And this is the full state-by-state, brand-by-brand price breakdown, for anyone who wants
> to dig into where fuel is cheapest."

*(Keep this section brief — the route planner is the star; these three are "and there's more.")*

---

## 4. How it works — architecture (1.5–2 min)

**Action:** Switch to the README architecture diagram (or describe verbally).

> "A route request only ever makes one external HTTP call if you give coordinates, or up to
> three if you give place names — two geocoding lookups plus one routing call. Everything
> else — matching stations to the route, running the optimizer — happens in memory or against
> the database, which is why repeat or nearby requests are fast."

**Corridor matching (the clever bit, if time allows):**
> "Instead of checking each of the 6,700 stations against the route one at a time, the route
> itself becomes a small spatial index — densified to about one point every 2 miles — and
> then *every station is matched against it in a single batched query* using scipy's cKDTree.
> That one call returns, for every station, its nearest point on the route and how far off the
> highway it is. Anything past a 10-mile detour radius gets dropped."

**Caching:**
> "Responses are cached, and the cache key includes a `price_version` number that bumps every
> time fuel prices are reloaded — so a price update automatically invalidates exactly the
> right cached routes, no manual purge logic needed."

---

## 5. Data pipeline & correctness (1 min, optional — trim if short on time)

> "The underlying data is a real 8,151-row fuel-price CSV, deduped down to 6,738 stations,
> geocoded entirely offline — no live geocoding API — using a bundled city/ZIP dataset, with a
> state-centroid fallback for the ~1.7% that don't match. The loader is idempotent: running it
> twice produces zero new stations and zero price updates, and price changes are appended to an
> audit-log table rather than overwriting history."

> "It's backed by 80 tests — dedupe/upsert idempotency, corridor matching, every branch of the
> optimizer, the API error cases — all against synthetic data, no network calls, runs in about
> a second."

---

## 6. Close (30 sec)

> "So: Django + PostgreSQL on the backend, scipy for the spatial matching, a public OSRM
> server for routing, all deployed on Cloud Run. No framework on the frontend — vanilla JS and
> Leaflet. The whole thing answers one question well: given a start and a finish, what's the
> cheapest way to fuel this trip — and it does it against real data, with a provably optimal
> algorithm, in under two seconds."

---

## Anticipated Q&A

| Question | Answer |
|---|---|
| Why greedy and not DP/ILP? | Greedy is optimal here because cost only depends on price and detour, not on interactions between stops — it's proven with an exchange argument in the README. DP would solve the same problem with more complexity for no better answer. |
| What if a route has a fuel gap with no reachable station? | Returns HTTP 422 with the exact mile marker and shortfall, rather than failing silently. |
| Is routing/geocoding rate-limited? | Yes — public OSRM/Nominatim, no API key, best-effort. Noted as a real production gap; a paid/self-hosted service would be needed at scale. |
| Does it handle Canada? | ~620 border-adjacent Canadian stations are included via province-centroid geocoding rather than dropped. |
| Is mpg/tank range configurable? | Yes, via `MPG` / `TANK_RANGE_MILES` env vars — currently fixed constants, no per-vehicle model. |
| How fresh are prices? | Single CSV snapshot loaded once; the schema supports a real price history over time, but there's no live feed yet — that's why the dashboard has no time-series chart. |

---

## Setup checklist before presenting

- [ ] Confirm live demo URL loads: https://trucker-319172055462.us-east4.run.app
- [ ] Pre-pick a short trip (no stops) and a long trip (multiple stops) so you're not typing live
- [ ] Have the README architecture diagram open in a second tab/window as backup visual
- [ ] Test on the actual presentation wifi beforehand — OSRM/Nominatim calls need network
