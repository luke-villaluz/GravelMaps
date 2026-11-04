"""US state extracts available from Geofabrik."""

US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "district-of-columbia", "florida", "georgia", "hawaii", "idaho", "illinois",
    "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts",
    "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new-hampshire", "new-jersey", "new-mexico", "new-york", "north-carolina", "north-dakota",
    "ohio", "oklahoma", "oregon", "pennsylvania", "puerto-rico", "rhode-island",
    "south-carolina", "south-dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west-virginia", "wisconsin", "wyoming",
]


ABBREVIATIONS = dict(zip(
    "al ak az ar ca co ct de dc fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj "
    "nm ny nc nd oh ok or pa pr ri sc sd tn tx ut vt va wa wv wi wy".split(),
    US_STATES,
))


def normalize(name):
    name = name.strip().lower().replace(" ", "-").replace("_", "-")
    return ABBREVIATIONS.get(name, name)


def url_for(region):
    return f"https://download.geofabrik.de/north-america/us/{region}-latest.osm.pbf"


def parse_list(text):
    """Parse 'nevada, New Mexico, CA' -> ['nevada', 'new-mexico', 'california']; raises ValueError on unknown names."""
    regions = [normalize(r) for r in text.split(",") if r.strip()]
    bad = [r for r in regions if r not in US_STATES]
    if bad:
        raise ValueError(f"Not a US state: {', '.join(bad)}")
    return list(dict.fromkeys(regions))
