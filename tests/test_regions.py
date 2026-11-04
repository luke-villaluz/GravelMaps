import pytest

from gravelmaps.regions import CODES, STATES, US_STATES, codes, parse_list


def test_codes():
    assert parse_list("ca") == ["california"]
    assert parse_list("ca nv  wa") == ["california", "nevada", "washington"]
    assert parse_list("ca,nv ca") == ["california", "nevada"]
    assert codes(["california", "new-mexico"]) == ["ca", "nm"]


def test_every_state_has_a_code():
    assert sorted(CODES) == sorted(US_STATES)
    assert len(STATES) == len(US_STATES)


@pytest.mark.parametrize("text", ["CA", "california", "cal", "c a"])
def test_only_lowercase_codes(text):
    with pytest.raises(ValueError):
        parse_list(text)
