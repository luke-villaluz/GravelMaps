import pytest

from gravelmaps.coords import parse

LAT, LON = 38.5733, -109.5498


@pytest.mark.parametrize("text", [
    "38.5733, -109.5498",
    "38.5733 -109.5498",
    "  38.5733,-109.5498 ",
    "N38 34.398 W109 32.988",           # Garmin default: degrees and decimal minutes
    "N 38° 34.398' W 109° 32.988'",
    "n38 34.398, w109 32.988",
    "38°34'23.9\"N 109°32'59.3\"W",     # Google Maps DMS
    "38° 34′ 23.9″ N, 109° 32′ 59.3″ W",
    "38.5733N 109.5498W",
    "38 34.398 -109 32.988",            # minutes without letters
])
def test_formats(text):
    lat, lon = parse(text)
    assert lat == pytest.approx(LAT, abs=1e-4) and lon == pytest.approx(LON, abs=1e-4)


def test_hemispheres():
    assert parse("S33 51.5 E151 12.5") == pytest.approx((-33.858333, 151.208333))
    assert parse("W109.5 N38.5") == pytest.approx((38.5, -109.5))  # longitude first is fine with letters


@pytest.mark.parametrize("text", [
    "", "Moab", "Moab, UT", "38.5", "N38 W109 E3", "N38 N109", "38 61 -109 0",   # minutes >= 60
    "91, 10", "10, 181", "N-38 W109", "38.5 34 -109 3", "1 2 3", "I-70 exit 182",
])
def test_rejects(text):
    assert parse(text) is None
