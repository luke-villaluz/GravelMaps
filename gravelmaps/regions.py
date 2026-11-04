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


CODES = dict(zip(
    US_STATES,
    "al ak az ar ca co ct de dc fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj "
    "nm ny nc nd oh ok or pa pr ri sc sd tn tx ut vt va wa wv wi wy".split(),
))
STATES = {code: name for name, code in CODES.items()}

HOW_TO = "Use lowercase two-letter state codes separated by spaces, like: ca nv wa"


def url_for(region):
    return f"https://download.geofabrik.de/north-america/us/{region}-latest.osm.pbf"


def parse_list(text):
    """Parse 'ca nv' (or 'ca,nv') -> ['california', 'nevada']; raises ValueError on anything else."""
    codes = text.replace(",", " ").split()
    bad = [c for c in codes if c not in STATES]
    if bad:
        raise ValueError(f"Not a state code: {' '.join(bad)}. {HOW_TO}")
    return list(dict.fromkeys(STATES[c] for c in codes))


def codes(regions):
    return [CODES[r] for r in regions]
