import json

import numpy as np

from gravelmaps import pois
from gravelmaps import tags as T


def write_fuel(path, rows):
    np.savez(path, fuel=np.frombuffer(json.dumps(rows).encode(), dtype=np.uint8))


def test_fuel_info():
    assert T.fuel_info({"amenity": "fuel", "brand": "Shell", "fuel:diesel": "yes", "opening_hours": "24/7"}) == \
        ["Shell", "Shell", "24/7", 1]
    assert T.fuel_info({"amenity": "fuel"}) == ["", "", "", None]


def test_build_dedupes_point_and_outline(tmp_path):
    # The same station as an unnamed outline and a named point 30 m away, in two state files.
    write_fuel(tmp_path / "a.npz", [[40.0, -118.0, "", "", "", None]])
    write_fuel(tmp_path / "b.npz", [[40.0002, -118.0002, "Chevron", "Chevron", "", 1],
                                    [40.1, -118.0, "Far", "", "", None]])
    out = tmp_path / "fuel.json"
    assert pois.build_fuel([tmp_path / "a.npz", tmp_path / "b.npz"], out) == 2
    assert sorted(r[2] for r in json.load(open(out))) == ["Chevron", "Far"]


def test_along_route_and_longest_gap(tmp_path):
    # East-west route along lat 40 from lon -118 to -117 (~85 km).
    rows = [
        [40.005, -117.9, "Near", "", "", None],    # ~0.55 km off route, ~8.5 km in
        [40.0, -117.2, "On", "", "", None],        # on route, ~68 km in
        [40.05, -117.5, "Too far", "", "", None],  # ~5.5 km off route
    ]
    path = tmp_path / "fuel.json"
    path.write_text(json.dumps(rows))
    idx = pois.FuelIndex(str(path))
    res = idx.along([[-118.0, 40.0], [-117.0, 40.0]])
    assert [s["name"] for s in res["stations"]] == ["Near", "On"]
    assert 400 < res["stations"][0]["off_m"] < 700
    gap = res["longest_gap"]
    assert not gap["from_start"] and not gap["to_end"]
    assert 58_000 < gap["length_m"] < 62_000  # between the two stations
    assert len(idx.in_bbox(39.9, -118.1, 40.01, -117.1)) == 2


def test_poi_kinds():
    kind = lambda **t: (T.poi_info(t) or [None, None])[:2]
    assert kind(tourism="camp_site", name="Forest Rd 12 Dispersed") == ["camp", "dispersed"]
    assert kind(tourism="camp_site", camp_type="wildcamp") == ["camp", "dispersed"]
    assert kind(tourism="camp_site", name="Oak Flat Campground") == ["camp", "campground"]
    assert kind(highway="trailhead", name="Rattlesnake OHV Staging Area") == ["trail", "staging"]
    assert kind(highway="trailhead", motorcycle="yes") == ["trail", "staging"]
    assert kind(highway="trailhead") == ["trail", "trailhead"]
    assert kind(highway="trailhead", name="Bradley Hills ORV Staging Area") == ["trail", "staging"]
    assert kind(highway="trailhead", name="Clayhill Horse Staging Area") == ["trail", "trailhead"]
    assert kind(amenity="parking", name="South Truck Staging Lot") == [None, None]
    assert kind(amenity="parking", name="Mill Creek Trailhead") == ["trail", "trailhead"]
    assert kind(amenity="parking") == [None, None]
    assert kind(man_made="water_tap", drinking_water="no") == [None, None]
    assert kind(natural="spring") == ["water", "spring"]
    assert kind(man_made="tower", **{"tower:type": "communication"}) == [None, None]
    assert kind(man_made="tower", name="Hat Point Lookout") == ["sight", "lookout"]
    assert kind(man_made="adit") == ["sight", "mine"]
    assert kind(**{"abandoned:place": "village", "name": "Rhyolite"}) == ["sight", "ghost_town"]
    assert kind(historic="archaeological_site", site_type="petroglyph") == ["sight", "petroglyph"]
    info = T.poi_info({"natural": "peak", "name": "Wheeler Peak", "ele": "13,065 ft"})[3]
    assert info == {"ele": 3982}
    info = T.poi_info({"tourism": "camp_site", "fee": "no", "toilets": "yes", "access": "private"})[3]
    assert info == {"fee": False, "toilets": True, "private": True}
    info = T.poi_info({"historic": "ruins", "ruins": "stamp_mill", "description": "Stone walls of the 1880s mill."})[3]
    assert info == {"desc": "Stone walls of the 1880s mill.", "what": "stamp mill"}
    assert T.poi_info({"man_made": "adit", "resource": "gold;silver"})[3] == {"what": "gold"}


def test_pois_priority_and_categories(tmp_path):
    rows = [[40.0, -118.0, "sight", "mine", "", {}],
            [40.0, -118.0002, "camp", "dispersed", "", {}],   # same spot, other category: kept
            [40.1, -118.0, "sight", "peak", "Big Peak", {"ele": 3000}],
            [40.1, -118.0002, "sight", "peak", "", {}]]        # unnamed duplicate of Big Peak
    np.savez(tmp_path / "a.npz", pois=np.frombuffer(json.dumps(rows).encode(), dtype=np.uint8))
    out = tmp_path / "pois.json"
    assert pois.build_pois([tmp_path / "a.npz"], out) == 3
    idx = pois.PoiIndex(str(out))
    got = idx.in_bbox(39, -119, 41, -117, ["peak", "mine"])
    assert [(p["kind"], p["name"]) for p in got] == [("peak", "Big Peak"), ("mine", "")]
    assert got[0]["ele"] == 3000
    assert [p["kind"] for p in idx.in_bbox(39, -119, 41, -117, ["dispersed", "spring"])] == ["dispersed"]


def test_pois_thinned_by_zoom(tmp_path):
    # Two springs ~30 m apart and a named campground next to them: at zoom 10 only the campground shows.
    # (Rows in the priority order build_pois writes them.)
    rows = [[40.0005, -118.0005, "camp", "campground", "Oak Flat", {}],
            [40.0, -118.0, "water", "spring", "", {}], [40.0003, -118.0, "water", "spring", "", {}]]
    path = tmp_path / "pois.json"
    path.write_text(json.dumps(rows))
    idx = pois.PoiIndex(str(path))
    assert [p["name"] for p in idx.in_bbox(39, -119, 41, -117, ["spring", "campground"], zoom=10)] == ["Oak Flat"]
    assert len(idx.in_bbox(39, -119, 41, -117, ["spring", "campground"])) == 3
