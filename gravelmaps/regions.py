"""US state extracts available from Geofabrik."""

DEFAULT_REGIONS = ["washington", "oregon", "california", "nevada", "arizona", "utah"]

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


def normalize(name):
    return name.strip().lower().replace(" ", "-").replace("_", "-")


def url_for(region):
    return f"https://download.geofabrik.de/north-america/us/{region}-latest.osm.pbf"


def parse_list(text):
    """Parse 'nevada, New Mexico' -> ['nevada', 'new-mexico']; raises ValueError on unknown names."""
    regions = [normalize(r) for r in text.split(",") if r.strip()]
    bad = [r for r in regions if r not in US_STATES]
    if bad:
        raise ValueError(f"Unknown region(s): {', '.join(bad)}")
    return list(dict.fromkeys(regions))
