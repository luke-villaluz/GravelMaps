import json

from gravelmaps import camping as C

# Wording copied from real motor vehicle use maps, legend text running into it as it does in the PDFs.
DIXIE = ("VICINITY MAP Dispersed Camping: Motor Vehicle use off of designated roads and/or trails for the purpose of "
         "dispersed camping is permitted for up to 150 feet from the centerline of all roads and/or trails from the "
         "period of 01/01 to 12/31. North American Datum of 1983")
BOISE = ("motor vehicle use off of designated roads and trails for the purposes of dispersed camping is permitted for up "
         "to 300 feet from the centerline of the road and 100 feet from the centerline of the trail when it is safe to do "
         "so. Dispersed camping not allowed in the Grimes Creek along roads 261 and 364 in sections 21,22,27. Roads remain open.")
MODOC = ("Seasonal Designation Table Dispersed Camping Motor vehicle use off of designated roads for the purpose of "
         "dispersed camping is permitted on National Forest Lands for up to 30 ft. from the centerline of the road.")
CLEVELAND = ("All routes with a seasonal designation are open to High Clearance Vehicles. Motorized vehicle use off "
             "designated roads and trails for the purpose of dispersed camping or game retrieval is not permitted on "
             "the Cleveland National Forest. North American Datum")
LEGEND_ONLY = ("Dispersed Camping/Game Retrieval: This symbol is used along with a designated road or trail to indicate "
               "limited cross-country motor vehicle use within a specific distance of that route, solely for the purpose "
               "of dispersed camping and/or game retrieval. The dots indicate where this activity is permitted.")


def test_forest_wide_rules():
    rules, prohibited, notes = C._camp_rules(DIXIE)
    assert [(r["applies"], r["ft"]) for r in rules] == [("both", 150)] and not prohibited and not notes

    rules, _, notes = C._camp_rules(BOISE)
    assert [(r["applies"], r["ft"]) for r in rules] == [("roads", 300), ("trails", 100)]
    assert notes == ["Dispersed camping not allowed in the Grimes Creek along roads 261 and 364 in sections 21,22,27"]

    rules, _, _ = C._camp_rules(MODOC)
    assert [(r["applies"], r["ft"]) for r in rules] == [("roads", 30)]


def test_prohibition_and_legend_boilerplate():
    rules, prohibited, _ = C._camp_rules(CLEVELAND)
    assert not rules and prohibited.startswith("Motorized vehicle use off designated roads")
    # The standard legend explains the dots on every map; it isn't a rule.
    assert C._camp_rules(LEGEND_ONLY) == ([], None, [])


def test_table_numbers_match_district_prefixed_ids():
    # Printed tables leave off the district prefix: '027A' on the Spanish Fork map is road 80027A.
    assert C._id_matches("80027A", ["027A"])
    assert C._id_matches("80621", ["621"])
    assert not C._id_matches("80621", ["21"])      # more than a two-digit prefix
    assert not C._id_matches("80027", ["027A"])


def test_dot_cover_and_side():
    # A road running east, with dots ~100 m north of it (its left side) along most of its length.
    road = [[[-111.0, 40.0], [-110.98, 40.0]]]
    dots = [(-111.0 + i * 0.001, 40.0009) for i in range(16)]
    grid = {}
    for x, y in dots:
        grid.setdefault((int(x // 0.01), int(y // 0.01)), []).append((x, y))
    cover, side = C._dot_cover(road, grid, 0.01)
    assert cover > 0.7 and side == "left"
    assert C._dot_cover(road, {}, 0.01) == (0.0, None)


def test_index_queries(tmp_path):
    sheet = {"i": 0, "forest": "Dixie National Forest", "title": "Pine Valley", "year": 2026, "url": "https://x/y.pdf",
             "area": [[[-114, 37], [-113, 37], [-113, 38], [-114, 38], [-114, 37]]], "rules": [], "prohibited": None,
             "notes": [], "tables": [], "dots": 0, "has_text": True}
    road = {"id": "30007", "name": "x", "t": "road", "s": "yes", "ft": 150, "how": "rule", "src": 0,
            "c": [[[-113.5, 37.5], [-113.49, 37.5]]]}
    path = tmp_path / "camping.json"
    path.write_text(json.dumps({"built": "2026-11-02", "sheets": [sheet], "roads": [road], "zones": [], "sites": []}))
    idx = C.CampingIndex(str(path))
    assert [r["id"] for r in idx.in_bbox(37.4, -113.6, 37.6, -113.4)["roads"]] == ["30007"]
    assert idx.in_bbox(36, -112, 36.5, -111.5)["roads"] == []
    at = idx.at(37.5, -113.5)
    assert at["sheets"][0]["title"] == "Pine Valley" and "one vehicle length" in at["sheets"][0]["roadside"]
    assert idx.at(36, -112)["sheets"] == []
