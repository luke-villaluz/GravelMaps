"""Turn OSM way tags into compact categorical attributes.

Costs live in profiles.py; this module only answers "what kind of road is this and who may
drive it". Changing anything here changes the per-state way caches, so bump PARSE_VERSION.
"""
import re

PARSE_VERSION = 15

# road_class codes
MOTORWAY, TRUNK, PRIMARY, SECONDARY, TERTIARY, UNCLASSIFIED, RESIDENTIAL, SERVICE, TRACK, PATH, ROAD = range(11)
ROAD_CLASS_NAMES = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
                    "residential", "service", "track", "path", "road"]

HIGHWAY_CLASS = {
    "motorway": MOTORWAY, "motorway_link": MOTORWAY,
    "trunk": TRUNK, "trunk_link": TRUNK,
    "primary": PRIMARY, "primary_link": PRIMARY,
    "secondary": SECONDARY, "secondary_link": SECONDARY,
    "tertiary": TERTIARY, "tertiary_link": TERTIARY,
    "unclassified": UNCLASSIFIED,
    "residential": RESIDENTIAL, "living_street": RESIDENTIAL,
    "service": SERVICE,
    "track": TRACK,
    "path": PATH, "bridleway": PATH, "footway": PATH, "cycleway": PATH,
    "road": ROAD,
}

# surface codes
PAVED, MAYBE_UNPAVED, UNPAVED = 0, 1, 2

UNPAVED_SURFACES = {
    "unpaved", "gravel", "fine_gravel", "compacted", "dirt", "earth", "ground", "sand", "grass",
    "mud", "pebblestone", "rock", "rocks", "stone", "shells", "salt", "snow", "ice", "woodchips",
    "clay", "soil", "gravel;dirt", "dirt;gravel", "grass_paver",
}
PAVED_SURFACES = {
    "paved", "asphalt", "concrete", "chipseal", "paving_stones", "sett", "cobblestone",
    "concrete:plates", "concrete:lanes", "bricks", "metal", "wood", "unhewn_cobblestone",
}
ROUGH_SURFACES = {"rock", "rocks", "sand", "mud", "stone"}
ROUGH_SMOOTHNESS = {"bad", "very_bad", "horrible", "very_horrible", "impassable"}
ROUGH_TRACKTYPES = {"grade4", "grade5"}

SKIP_SERVICE = {"driveway", "parking_aisle", "drive-through", "emergency_access"}

# Profile bits in legal_mask
CAR, MOTO = 1, 2

DENY = {"no", "private", "agricultural", "forestry", "delivery", "military", "restricted", "emergency",
        "permit", "unknown"}
ALLOW = {"yes", "designated", "permissive", "destination", "customers", "official"}


def _first_defined(tags, keys):
    for k in keys:
        v = tags.get(k)
        if v is not None:
            return v.split(";")[0].strip()
    return None


def _allowed(tags, keys, default):
    """Walk the OSM access hierarchy from most to least specific key."""
    v = _first_defined(tags, keys)
    if v is None:
        return default
    if v in DENY:
        return False
    if v in ALLOW:
        return True
    return default


def _metres(value):
    """Parse an OSM width like '2.5', '2 m' or 6'6\" into metres (inf if missing/unparseable)."""
    if not value:
        return float("inf")
    v = value.strip().lower()
    try:
        if "'" in v:
            ft, _, inch = v.partition("'")
            return float(ft) * 0.3048 + float(inch.strip('" ') or 0) * 0.0254
        return float(v.removesuffix("m").strip())
    except ValueError:
        return float("inf")


def classify(tags):
    """Return (road_class, surface, rough, legal_mask, oneway) or None if the way is not routable.

    `tags` is any mapping with .get(); oneway is 1, -1 or 0.
    """
    hw = tags.get("highway")
    rc = HIGHWAY_CLASS.get(hw)
    if rc is None:
        return None
    if rc == SERVICE and tags.get("service") in SKIP_SERVICE:
        return None
    if tags.get("area") == "yes":
        return None
    if tags.get("disused") == "yes" or tags.get("abandoned") == "yes":
        return None

    surface_tag = (tags.get("surface") or "").split(";")[0].strip()
    tracktype = tags.get("tracktype")
    smoothness = tags.get("smoothness")

    if surface_tag in UNPAVED_SURFACES:
        surface = UNPAVED
    elif surface_tag in PAVED_SURFACES or tracktype == "grade1":
        surface = PAVED
    elif rc in (TRACK, PATH) or tracktype in ("grade2", "grade3", "grade4", "grade5"):
        surface = UNPAVED
    elif rc in (UNCLASSIFIED, ROAD):
        surface = MAYBE_UNPAVED
    else:
        surface = PAVED

    four_wd = tags.get("4wd_only") == "yes"
    rough = int(
        four_wd
        or tracktype in ROUGH_TRACKTYPES
        or smoothness in ROUGH_SMOOTHNESS
        or surface_tag in ROUGH_SURFACES
    )

    legal = 0
    if rc == PATH:
        # Trails are off-limits to motor vehicles unless explicitly opened.
        if _allowed(tags, ["motorcar", "motor_vehicle"], False) or (four_wd and _allowed(tags, ["motor_vehicle"], True)):
            legal |= CAR
        if (_allowed(tags, ["motorcycle", "motor_vehicle"], False)
                or (_allowed(tags, ["ohv", "atv"], False) and _allowed(tags, ["motorcycle"], True))):
            legal |= MOTO
    else:
        if _allowed(tags, ["motorcar", "motor_vehicle", "vehicle", "access"], True):
            legal |= CAR
        # Dual sports also get roads opened to OHVs/ATVs even when closed to street vehicles.
        if (_allowed(tags, ["motorcycle", "motor_vehicle", "vehicle", "access"], True)
                or (_allowed(tags, ["ohv", "atv"], False) and _allowed(tags, ["motorcycle"], True))):
            legal |= MOTO
    # Physically too rough or narrow for a car, fine on a bike.
    if smoothness == "impassable" or _metres(tags.get("maxwidth")) < 1.8:
        legal &= ~CAR
    if not legal:
        return None

    ow = tags.get("oneway")
    if ow in ("yes", "true", "1"):
        oneway = 1
    elif ow == "-1" or ow == "reverse":
        oneway = -1
    elif ow == "no":
        oneway = 0
    elif rc == MOTORWAY or tags.get("junction") in ("roundabout", "circular"):
        oneway = 1
    else:
        oneway = 0

    return rc, surface, rough, legal, oneway


# Road detail for hover text, packed into a uint16 per way: surface tag (bits 0-5, index into
# DETAIL_SURFACES + 1), tracktype grade (6-8), smoothness (9-12, index into SMOOTHNESS + 1), 4wd_only (13).
DETAIL_SURFACES = sorted(UNPAVED_SURFACES | PAVED_SURFACES)
SMOOTHNESS = ["excellent", "good", "intermediate", "bad", "very_bad", "horrible", "very_horrible", "impassable"]
SMOOTHNESS_TEXT = ["smooth", "any car", "fine for any car", "OK for a normal car, slowly", "high clearance needed",
                   "4x4 needed", "extreme 4x4 / ATV only", "no vehicles"]
TRACKTYPE_TEXT = ["", "grade 1: paved or heavily compacted", "grade 2: mostly gravel", "grade 3: mix of hard and soft",
                  "grade 4: mostly soft dirt or grass", "grade 5: soft, unimproved"]


def detail_code(tags):
    surface = (tags.get("surface") or "").split(";")[0].strip()
    code = DETAIL_SURFACES.index(surface) + 1 if surface in DETAIL_SURFACES else 0
    tt = tags.get("tracktype") or ""
    if len(tt) == 6 and tt.startswith("grade") and tt[5] in "12345":
        code |= int(tt[5]) << 6
    sm = tags.get("smoothness")
    if sm in SMOOTHNESS:
        code |= (SMOOTHNESS.index(sm) + 1) << 9
    if tags.get("4wd_only") == "yes":
        code |= 1 << 13
    return code


def describe_detail(code):
    """Plain-English lines for a way's detail code: what OSM says about its surface and condition."""
    out = []
    surface = code & 63
    if surface:
        out.append("Surface: " + DETAIL_SURFACES[surface - 1].replace("_", " "))
    grade = (code >> 6) & 7
    if grade:
        out.append("Track " + TRACKTYPE_TEXT[grade])
    sm = (code >> 9) & 15
    if sm:
        out.append("Smoothness: " + SMOOTHNESS[sm - 1].replace("_", " ") + " (" + SMOOTHNESS_TEXT[sm - 1] + ")")
    if code >> 13 & 1:
        out.append("Tagged 4WD only")
    return out


def display_name(tags):
    name = tags.get("name")
    ref = tags.get("ref")
    if name and ref:
        return f"{name} ({ref})"
    return name or ref or ""


# Searchable points: (tag key, tag value, label). Order = search rank, most important first.
PLACE_TYPES = [
    ("place", "city", "City"),
    ("place", "town", "Town"),
    ("place", "village", "Village"),
    ("place", "hamlet", "Hamlet"),
    ("historic", "ghost_town", "Ghost Town"),
    ("tourism", "camp_site", "Campground"),
    ("amenity", "fuel", "Gas Station"),
    ("highway", "trailhead", "Trailhead"),
    ("natural", "peak", "Peak"),
    ("natural", "hot_spring", "Hot Spring"),
    ("leisure", "hot_spring", "Hot Spring"),
    ("place", "suburb", "Neighborhood"),
    ("place", "neighbourhood", "Neighborhood"),
    ("place", "locality", "Locality"),
    ("natural", "spring", "Spring"),
    ("tourism", "viewpoint", "Viewpoint"),
    ("tourism", "wilderness_hut", "Cabin"),
    ("historic", "mine", "Mine"),
    ("historic", "ruins", "Ruins"),
    ("natural", "arch", "Arch"),
    ("tourism", "hotel", "Hotel"),
    ("tourism", "motel", "Motel"),
]
PLACE_TAGS = [(k, v) for k, v, _ in PLACE_TYPES]
FUEL_TAG = ("amenity", "fuel")
PLACE_LABELS = [label for _, _, label in PLACE_TYPES]


def place_type(tags):
    """Index into PLACE_TYPES for a searchable node, or None."""
    for i, (k, v) in enumerate(PLACE_TAGS):
        if tags.get(k) == v:
            return i
    return None


def fuel_info(tags):
    """Details kept for a gas station: [name, brand, opening hours, diesel (1/0/None)]."""
    diesel = tags.get("fuel:diesel")
    return [tags.get("name") or tags.get("brand") or "", tags.get("brand") or "", tags.get("opening_hours") or "",
            1 if diesel in ("yes", "only") else 0 if diesel == "no" else None]


# Map points of interest, one map layer per category. A kind picks the icon; order = priority when
# a view holds more than the server returns (earlier categories and kinds win).
POI_KINDS = {
    "camp": ["dispersed", "campground", "cabin", "rv"],
    "water": ["water", "spring"],
    "trail": ["staging", "trailhead"],
    "lodging": ["motel", "hotel", "inn", "hostel", "rental"],
    "sight": ["hot_spring", "ghost_town", "lookout", "arch", "petroglyph", "viewpoint", "peak", "cave", "ruins", "mine"],
}
POI_RANK = {k: i for i, k in enumerate(k for kinds in POI_KINDS.values() for k in kinds)}
# Ghost towns are mostly mapped as abandoned:place=town/village/... rather than historic=ghost_town.
ABANDONED_PLACES = ["city", "town", "village", "hamlet", "locality", "isolated_dwelling"]
# OSM tourism values that are a bed for the night, and the marker kind each gets.
LODGING = {"hotel": "hotel", "motel": "motel", "guest_house": "inn", "hostel": "hostel", "chalet": "rental",
           "apartment": "rental"}
# Node tags worth a look (the C++ filter needs exact key/value pairs); outlines are matched by key.
POI_NODE_TAGS = [
    ("amenity", "drinking_water"), ("amenity", "water_point"), ("man_made", "water_tap"), ("natural", "spring"),
    ("tourism", "camp_site"), ("tourism", "caravan_site"), ("tourism", "wilderness_hut"), ("tourism", "alpine_hut"),
    ("amenity", "shelter"), ("highway", "trailhead"), ("amenity", "parking"),
    ("historic", "ghost_town"), *[("abandoned:place", v) for v in ABANDONED_PLACES],
    ("historic", "mine"), ("historic", "mine_shaft"), ("historic", "mine_adit"),
    ("man_made", "mineshaft"), ("man_made", "adit"), ("historic", "ruins"), ("historic", "archaeological_site"),
    ("historic", "rock_art"), ("tourism", "viewpoint"), ("natural", "peak"), ("natural", "volcano"),
    ("man_made", "tower"), ("natural", "hot_spring"), ("leisure", "hot_spring"), ("natural", "arch"),
    ("natural", "cave_entrance"),
    *[("tourism", v) for v in LODGING],
]
POI_WAY_KEYS = ["tourism", "historic", "man_made"]
DISPERSED_TYPES = {"wildcamp", "non_designated", "dispersed", "informal"}
YES = {"yes", "designated", "permissive"}
OHV_NAME = re.compile(r"\b(ohv|orv|ohmvr|off[- ]highway|off[- ]road|motorcycle|atv|utv|4x4|4wd|jeep)\b")
NOT_OHV_NAME = re.compile(r"\b(horse|equestrian|truck|bus)\b")


def _poi_kind(tags):
    g = tags.get
    name = (g("name") or "").lower()
    amenity, tourism, historic, man_made, natural = g("amenity"), g("tourism"), g("historic"), g("man_made"), g("natural")
    if amenity in ("drinking_water", "water_point") or (man_made == "water_tap" and g("drinking_water") != "no"):
        return "water", "water"
    if natural == "spring":
        return "water", "spring"
    if tourism == "camp_site":
        dispersed = (g("camp_type") in DISPERSED_TYPES or g("backcountry") == "yes" or g("informal") == "yes"
                     or g("impromptu") == "yes" or "dispersed" in name)
        return "camp", "dispersed" if dispersed else "campground"
    if tourism == "caravan_site":
        return "camp", "rv"
    if tourism in ("wilderness_hut", "alpine_hut") or (amenity == "shelter" and g("shelter_type") == "basic_hut"):
        return "camp", "cabin"
    if tourism in LODGING:
        return "lodging", LODGING[tourism]
    ohv = any(g(k) in YES for k in ("ohv", "atv", "motorcycle", "off_road"))
    if g("highway") == "trailhead" or (amenity == "parking" and ("trailhead" in name or "staging" in name)):
        staging = ohv or OHV_NAME.search(name) or ("staging" in name and not NOT_OHV_NAME.search(name))
        if amenity == "parking" and "trailhead" not in name and not staging:
            return None
        return "trail", "staging" if staging else "trailhead"
    if historic == "ghost_town" or (g("abandoned:place") in ABANDONED_PLACES and g("name")):
        return "sight", "ghost_town"
    if man_made == "tower" and (g("tower:type") == "fire_lookout" or "lookout" in name):
        return "sight", "lookout"
    if natural == "hot_spring" or g("leisure") == "hot_spring":
        return "sight", "hot_spring"
    if natural == "arch":
        return "sight", "arch"
    if historic == "rock_art" or (historic == "archaeological_site"
                                  and (g("site_type") in ("petroglyph", "rock_art")
                                       or g("archaeological_site") in ("petroglyph", "rock_art"))):
        return "sight", "petroglyph"
    if tourism == "viewpoint":
        return "sight", "viewpoint"
    if natural in ("peak", "volcano"):
        return "sight", "peak"
    if natural == "cave_entrance":
        return "sight", "cave"
    if historic == "ruins":
        return "sight", "ruins"
    if historic in ("mine", "mine_shaft", "mine_adit") or man_made in ("mineshaft", "adit"):
        return "sight", "mine"
    return None


def _ele_m(value):
    try:
        v = value.replace(",", "").strip()
        return round(float(v[:-2]) * 0.3048) if v.endswith(("ft", "'")) else round(float(v.rstrip("m ")))
    except (AttributeError, ValueError):
        return None


def poi_info(tags):
    """[category, kind, name, details] for a map point of interest, or None. Details only hold what's set."""
    hit = _poi_kind(tags)
    if hit is None:
        return None
    g = tags.get
    info = {}
    if g("fee") in ("yes", "no"):
        info["fee"] = g("fee") == "yes"
    for key, tag in (("toilets", "toilets"), ("water", "drinking_water")):
        if g(tag) in ("yes", "no"):
            info[key] = g(tag) == "yes"
    if g("seasonal") not in (None, "no"):
        info["seasonal"] = g("seasonal") if g("seasonal") != "yes" else ""
    if g("access") in ("private", "no"):
        info["private"] = True
    for key, tag in (("operator", "operator"), ("url", "website"), ("hours", "opening_hours")):
        if g(tag):
            info[key] = g(tag)[:120]
    if g("reservation") in ("required", "yes", "no"):
        info["reservation"] = g("reservation")
    if hit[0] == "lodging":
        phone = g("phone") or g("contact:phone")
        if phone:
            info["phone"] = phone.split(";")[0].strip()[:30]
        stars = (g("stars") or "")[:1]
        if stars and stars in "12345":
            info["stars"] = int(stars)
    if not info.get("url") and g("contact:website"):
        info["url"] = g("contact:website")[:120]
    ele = _ele_m(g("ele"))
    if ele is not None:
        info["ele"] = ele
    desc = (g("description") or "").strip()
    if desc:
        info["desc"] = desc if len(desc) <= 300 else desc[:299].rsplit(" ", 1)[0] + "…"
    # What a ruin used to be, or what a mine dug for (ruins=mill, resource=gold).
    what = g("ruins") if hit[1] == "ruins" else g("resource") if hit[1] == "mine" else None
    if what and what not in ("yes", "no"):
        info["what"] = what.replace("_", " ").split(";")[0][:40]
    return [*hit, g("name") or "", info]


def place_name(tags):
    return tags.get("name") or tags.get("brand") or ""


# Barrier nodes. Value = passable by default? Gates are usually open (cattle gates on public land);
# the rest physically stop a vehicle unless the barrier's own access tags say otherwise.
BARRIERS = {
    "gate": True, "lift_gate": True, "swing_gate": True, "sliding_gate": True, "cattle_grid": True,
    "bollard": False, "block": False, "jersey_barrier": False, "chain": False, "debris": False,
    "log": False, "kissing_gate": False, "stile": False, "turnstile": False,
    "full-height_turnstile": False, "motorcycle_barrier": False, "barrier_board": False,
}
BARRIER_TAGS = [("barrier", v) for v in BARRIERS]
OPEN_STATES = {"open", "yes"}


def barrier_blocks(tags):
    """Bitmask of profiles (CAR/MOTO) that cannot pass this barrier node; 0 if passable."""
    kind = tags.get("barrier")
    if kind not in BARRIERS:
        return 0
    default = BARRIERS[kind]
    if tags.get("locked") == "yes":
        default = False
    blocked = 0
    if not _allowed(tags, ["motorcar", "motor_vehicle", "vehicle", "access"], default):
        blocked |= CAR
    if not _allowed(tags, ["motorcycle", "motor_vehicle", "vehicle", "access"], default):
        blocked |= MOTO
    if tags.get("locked") == "yes":  # a key holder's "yes" doesn't help us
        blocked |= CAR | MOTO
    return blocked
