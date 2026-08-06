(function () {
  "use strict";

  var API_URL = "/api/route/";

  var ICONS = {
    warn: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#f0b755" stroke-width="1.9" stroke-linecap="round"><path d="M12 3l9.5 16.5h-19z"/><path d="M12 10v4M12 17.2v.1"/></svg>',
    err: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#a98ce0" stroke-width="1.9" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6M8.5 11h5"/></svg>'
  };

  var el = {};
  ["planForm", "start", "finish", "planBtn", "planTxt",
   "stateIdle", "stateLoading", "stateError", "stateResult",
   "errTitle", "errBody", "errWhy", "errIconWrap",
   "sumDistance", "sumCost", "sumStops", "sumAvg", "listMeta", "stopList",
   "mapOverlay", "mapBadge", "badgeRoute", "badgeStats", "legend"
  ].forEach(function (id) { el[id] = document.getElementById(id); });

  var map, routeLine, routeOutline, stopMarkers = [], originMarker, destMarker;
  var selectedIndex = null, currentStops = [];

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s === null || s === undefined ? "" : String(s);
    return div.innerHTML;
  }

  function fmtMoney(n) { return "$" + Number(n).toFixed(2); }
  function fmtMiles(n) { return Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 }) + " mi"; }

  function initMap() {
    map = L.map("map", { zoomControl: false, attributionControl: true, scrollWheelZoom: true }).setView([39.5, -98.35], 4);
    L.control.zoom({ position: "topright" }).addTo(map);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);
  }

  function markerIcon(label, opts) {
    opts = opts || {};
    var cls = "mk" + (opts.selected ? " sel" : "") + (opts.end ? " end" : "");
    return L.divIcon({ className: "", html: '<div class="' + cls + '">' + label + "</div>", iconSize: [26, 26], iconAnchor: [13, 13] });
  }

  function setState(name) {
    ["Idle", "Loading", "Error", "Result"].forEach(function (n) { el["state" + n].classList.add("hidden"); });
    el["state" + name].classList.remove("hidden");
    var loading = name === "Loading";
    el.planBtn.disabled = loading;
    el.planTxt.textContent = loading ? "Optimizing…" : "Plan route";
    el.planForm.style.opacity = loading ? ".6" : "1";
    el.mapOverlay.classList.toggle("show", loading);
  }

  function clearMap() {
    if (routeLine) { map.removeLayer(routeLine); routeLine = null; }
    if (routeOutline) { map.removeLayer(routeOutline); routeOutline = null; }
    stopMarkers.forEach(function (m) { map.removeLayer(m); });
    stopMarkers = [];
    if (originMarker) { map.removeLayer(originMarker); originMarker = null; }
    if (destMarker) { map.removeLayer(destMarker); destMarker = null; }
    el.mapBadge.classList.add("hidden");
    el.legend.classList.add("hidden");
  }

  function popupHtml(stop) {
    return '<div class="popup">' +
      '<p class="pname">' + escapeHtml(stop.name) + '</p>' +
      '<p class="ploc">' + escapeHtml(stop.address) + ', ' + escapeHtml(stop.city) + ', ' + escapeHtml(stop.state) + '</p>' +
      '<div class="prow"><span>Price</span><b>' + fmtMoney(stop.price_per_gallon) + '/gal</b></div>' +
      '<div class="prow"><span>Gallons</span><b>' + stop.gallons.toFixed(1) + '</b></div>' +
      '<div class="prow"><span>Cost</span><b>' + fmtMoney(stop.cost) + '</b></div>' +
      '<div class="prow"><span>Mile marker</span><b>' + Math.round(stop.miles_from_start) + '</b></div>' +
      '<div class="prow"><span>Detour</span><b>' + stop.detour_miles.toFixed(1) + ' mi</b></div>' +
      '</div>';
  }

  function selectStop(index) {
    selectedIndex = index;
    stopMarkers.forEach(function (m, i) { m.setIcon(markerIcon(i + 1, { selected: i === index })); });
    renderList();
    var stop = currentStops[index];
    if (stop) {
      map.flyTo([stop.latitude, stop.longitude], 7, { duration: 0.6 });
      stopMarkers[index].openPopup();
    }
  }

  function renderList() {
    if (!currentStops.length) {
      el.stopList.innerHTML = '';
      return;
    }
    el.stopList.innerHTML = currentStops.map(function (s, i) {
      return '<button type="button" class="stop' + (selectedIndex === i ? ' on' : '') + '" data-i="' + i + '">' +
        '<span class="pin">' + (i + 1) + '</span>' +
        '<span>' +
          '<span class="sname">' + escapeHtml(s.name) + '</span>' +
          '<span class="sloc">' + escapeHtml(s.city) + ', ' + escapeHtml(s.state) + ' · mile ' + Math.round(s.miles_from_start) + '</span>' +
          '<span class="sprice">' + fmtMoney(s.price_per_gallon) + '/gal</span>' +
        '</span>' +
        '<span class="sright">' +
          '<span class="sgal">' + s.gallons.toFixed(1) + ' gal</span>' +
          '<span class="scost">' + fmtMoney(s.cost) + '</span>' +
          '<span class="sdetour">' + (s.detour_miles > 0 ? s.detour_miles.toFixed(1) + ' mi detour' : 'on route') + '</span>' +
        '</span>' +
      '</button>';
    }).join('');
    el.stopList.querySelectorAll(".stop").forEach(function (btn) {
      btn.addEventListener("click", function () { selectStop(Number(btn.dataset.i)); });
    });
  }

  function renderSummary(data, startLabel, finishLabel) {
    var stops = data.fuel_stops;
    var totalGallons = stops.reduce(function (sum, s) { return sum + s.gallons; }, 0);

    el.sumDistance.textContent = fmtMiles(data.total_distance_miles);
    el.sumStops.textContent = stops.length;

    if (stops.length) {
      el.sumCost.textContent = fmtMoney(data.total_fuel_cost);
      el.sumAvg.textContent = fmtMoney(data.total_fuel_cost / totalGallons);
      el.listMeta.textContent = totalGallons.toFixed(1) + ' gal · avg ' + fmtMoney(data.total_fuel_cost / totalGallons) + '/gal';
    } else if (data.estimated_trip_cost !== undefined && data.estimated_trip_cost !== null) {
      el.sumCost.textContent = '~' + fmtMoney(data.estimated_trip_cost);
      el.sumAvg.textContent = '—';
      el.listMeta.textContent = 'Fits in one tank — no stop needed';
    } else {
      el.sumCost.textContent = fmtMoney(0);
      el.sumAvg.textContent = '—';
      el.listMeta.textContent = 'Fits in one tank — no stop needed';
    }

    el.badgeRoute.innerHTML = escapeHtml(startLabel) + ' <b>&rarr;</b> ' + escapeHtml(finishLabel);
    el.badgeStats.innerHTML = '<b>' + Math.round(data.total_distance_miles).toLocaleString() + '</b> mi · <b>' + stops.length + '</b> stop' + (stops.length === 1 ? '' : 's');
    el.mapBadge.classList.remove("hidden");
    el.legend.classList.remove("hidden");
  }

  function renderMap(data, startLabel, finishLabel) {
    clearMap();

    var routeLatLngs = data.route.coordinates.map(function (pair) { return [pair[1], pair[0]]; });

    if (routeLatLngs.length) {
      routeOutline = L.polyline(routeLatLngs, { color: "#ffffff", weight: 8, opacity: 0.75, lineJoin: "round" }).addTo(map);
      routeLine = L.polyline(routeLatLngs, { color: "#0e2338", weight: 4, opacity: 0.95, lineJoin: "round" }).addTo(map);

      originMarker = L.marker(routeLatLngs[0], { icon: markerIcon("S") }).addTo(map)
        .bindTooltip(startLabel, { permanent: true, direction: "right", className: "mlbl", offset: [14, 0] });
      destMarker = L.marker(routeLatLngs[routeLatLngs.length - 1], { icon: markerIcon("&#9635;", { end: true }) }).addTo(map)
        .bindTooltip(finishLabel, { permanent: true, direction: "bottom", className: "mlbl", offset: [0, 10] });
    }

    stopMarkers = data.fuel_stops.map(function (s, i) {
      var m = L.marker([s.latitude, s.longitude], { icon: markerIcon(i + 1) }).addTo(map);
      m.bindPopup(popupHtml(s));
      m.on("click", function () { selectStop(i); });
      return m;
    });

    if (routeLatLngs.length) {
      map.flyToBounds(L.latLngBounds(routeLatLngs), { padding: [64, 64], duration: 0.6 });
    }
  }

  function describeError(status, body) {
    if (status === 400) {
      var fieldErrors = [];
      if (body && body.error && typeof body.error === "object") {
        Object.keys(body.error).forEach(function (field) {
          var msgs = Array.isArray(body.error[field]) ? body.error[field] : [String(body.error[field])];
          fieldErrors.push(field + ": " + msgs.join(" "));
        });
      }
      return {
        icon: "warn",
        title: "Check your locations",
        body: fieldErrors.length ? fieldErrors.join(" · ") : "Start and destination are both required."
      };
    }
    if (status === 404) {
      return {
        icon: "err",
        title: "Location not found",
        body: (body && body.error) || "We couldn't geocode one of those locations. Try a more specific city and state."
      };
    }
    if (status === 422) {
      return {
        icon: "warn",
        title: "Route not fully coverable",
        body: (body && body.error) || "No fuel station is reachable somewhere along this route within the tank range."
      };
    }
    if (status === 502) {
      return {
        icon: "err",
        title: "Routing service unavailable",
        body: (body && body.error) || "The routing or geocoding service didn't respond. Try again in a moment."
      };
    }
    return {
      icon: "err",
      title: "Something went wrong",
      body: (body && body.error && String(body.error)) || "Couldn't reach the server. Check your connection and try again."
    };
  }

  function showError(status, body) {
    var info = describeError(status, body);
    el.errIconWrap.className = "msgicon " + info.icon;
    el.errIconWrap.innerHTML = ICONS[info.icon];
    el.errTitle.textContent = info.title;
    el.errBody.textContent = info.body;
    el.errWhy.classList.add("hidden");
    setState("Error");
    clearMap();
    el.mapBadge.classList.add("hidden");
    el.legend.classList.add("hidden");
  }

  function planRoute(event) {
    event.preventDefault();
    var start = el.start.value.trim();
    var finish = el.finish.value.trim();
    if (!start || !finish) { return; }

    setState("Loading");
    selectedIndex = null;

    fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start: start, finish: finish })
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { ok: res.ok, status: res.status, body: body };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          showError(result.status, result.body);
          return;
        }
        var data = result.body;
        currentStops = data.fuel_stops;
        renderSummary(data, start, finish);
        renderMap(data, start, finish);
        renderList();
        setState("Result");
      })
      .catch(function () {
        showError(0, null);
      });
  }

  el.planForm.addEventListener("submit", planRoute);

  initMap();
  setState("Idle");
})();
