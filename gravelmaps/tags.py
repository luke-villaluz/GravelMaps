"""Turn OSM way tags into compact categorical attributes.

Costs live in profiles.py; this module only answers "what kind of road is this and who may
drive it". Changing anything here changes the per-state way caches, so bump PARSE_VERSION.
"""

PARSE_VERSION = 4

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
]
PLACE_TAGS = [(k, v) for k, v, _ in PLACE_TYPES]
PLACE_LABELS = [label for _, _, label in PLACE_TYPES]


def place_type(tags):
    """Index into PLACE_TYPES for a searchable node, or None."""
    for i, (k, v) in enumerate(PLACE_TAGS):
        if tags.get(k) == v:
            return i
    return None


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
