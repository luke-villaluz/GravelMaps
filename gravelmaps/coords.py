"""Parse typed coordinates, in the formats GPS units and maps show them.

  38.5733, -109.5498                 decimal degrees
  N38 34.398 W109 32.988             degrees and decimal minutes (Garmin's default)
  N 38° 34.398' W 109° 32.988'       the same, with symbols
  38°34'23.9"N 109°32'59.3"W         degrees, minutes, seconds (Google Maps)
  38.5733N 109.5498W                 decimal degrees with hemisphere letters
"""
import re

_SYMBOLS = re.compile("[°º˚'′’\"″”]")
_ALLOWED = re.compile(r"^[0-9NSEW.,\-\s]+$")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _value(nums):
    """[deg], [deg, min] or [deg, min, sec] -> signed degrees, or None."""
    if not 1 <= len(nums) <= 3:
        return None
    try:
        parts = [float(n) for n in nums]
    except ValueError:
        return None
    deg, rest = parts[0], parts[1:]
    if rest:
        # Minutes and seconds only follow whole degrees, and stay under 60.
        if deg != int(deg) or any(not 0 <= r < 60 for r in rest) or any(r != int(r) for r in rest[:-1]):
            return None
    mag = abs(deg) + sum(r / 60 ** (i + 1) for i, r in enumerate(rest))
    return -mag if nums[0].startswith("-") else mag


def parse(text):
    """(lat, lon) for a typed coordinate pair, or None if it isn't one."""
    s = _SYMBOLS.sub(" ", text.upper()).strip()
    if not s or not _ALLOWED.match(s):
        return None
    letters = re.findall(r"[NSEW]", s)
    if letters:
        if len(letters) != 2 or {letters[0] in "NS", letters[1] in "NS"} != {True, False}:
            return None
        pieces = [p for p in re.split(r"([NSEW])", s) if p.strip(" ,")]
        if len(pieces) != 4:
            return None
        if pieces[0] in "NSEW":       # N38 34.398 W109 32.988
            groups = [(pieces[0], pieces[1]), (pieces[2], pieces[3])]
        elif pieces[1] in "NSEW":     # 38 34 23.9 N 109 32 59.3 W
            groups = [(pieces[1], pieces[0]), (pieces[3], pieces[2])]
        else:
            return None
        lat = lon = None
        for hemi, body in groups:
            nums = _NUMBER.findall(body)
            if "".join(nums) != "".join(body.replace(",", " ").split()) or any(n.startswith("-") for n in nums):
                return None  # stray characters, or a minus sign fighting the letter
            v = _value(nums)
            if v is None:
                return None
            if hemi in "SW":
                v = -v
            if hemi in "NS":
                lat = v
            else:
                lon = v
    else:
        halves = s.split(",")
        if len(halves) == 2:
            groups = [_NUMBER.findall(h) for h in halves]
            if any("".join(g) != "".join(h.split()) for g, h in zip(groups, halves)):
                return None
        else:
            nums = _NUMBER.findall(s)
            if len(halves) != 1 or "".join(nums) != "".join(s.split()) or len(nums) not in (2, 4, 6):
                return None
            groups = [nums[:len(nums) // 2], nums[len(nums) // 2:]]
        lat, lon = _value(groups[0]), _value(groups[1])
        if lat is None or lon is None:
            return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon
