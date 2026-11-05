// Pure geometry and fuel planning, with no DOM or Leaflet, so tests can run them in Node.

/** Starting on a full tank, drive to the farthest station still in range and fill up there. Where
 * the next station (or the end) is out of reach, flag the stretch and carry on from that station.
 * A station under SAME_TOWN_M ahead is no progress (topping off in town), and none at the end counts. */
const SAME_TOWN_M = 3200;
export function planFuel(stations, total, range) {
  const fills = new Set(), short = [];
  let pos = 0, i = 0;
  while (total - pos > range + 1) { // +1 m: float slack when the end is exactly a tank away
    while (i < stations.length && stations[i].at_m <= pos + range + 1) i++;
    if (i > 0 && stations[i - 1].at_m > pos + SAME_TOWN_M) {
      fills.add(stations[i - 1]);
      pos = stations[i - 1].at_m;
      continue;
    }
    const next = i < stations.length ? stations[i].at_m : total;
    short.push({ from_m: pos, to_m: next });
    if (i >= stations.length) break;
    if (total - next > SAME_TOWN_M) fills.add(stations[i]);
    pos = next;
  }
  return { fills, short };
}

const toRad = Math.PI / 180;
export function haversine(lat1, lon1, lat2, lon2) {
  const a = Math.sin(((lat2 - lat1) * toRad) / 2) ** 2
    + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(((lon2 - lon1) * toRad) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(a));
}

/** The route's line between two distances along it, as Leaflet latlngs. */
export function routeSlice(r, from, to) {
  const coords = r.features.flatMap((f) => f.geometry.coordinates);
  const out = [];
  let d = 0;
  for (let k = 1; k < coords.length; k++) {
    const [plon, plat] = coords[k - 1], [lon, lat] = coords[k];
    const seg = haversine(plat, plon, lat, lon);
    const at = (m) => { const t = seg ? (m - d) / seg : 0; return [plat + (lat - plat) * t, plon + (lon - plon) * t]; };
    if (!out.length && d + seg >= from) out.push(at(from));
    if (d + seg >= to) { out.push(at(to)); break; }
    if (out.length) out.push([lat, lon]);
    d += seg;
  }
  return out;
}
