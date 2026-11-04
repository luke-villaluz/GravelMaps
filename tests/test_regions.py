import pytest

from gravelmaps.regions import ABBREVIATIONS, US_STATES, parse_list


def test_names_and_abbreviations():
    assert parse_list("CA") == ["california"]
    assert parse_list("california, NV, new mexico") == ["california", "nevada", "new-mexico"]
    assert parse_list("ca, California") == ["california"]


def test_every_state_has_an_abbreviation():
    assert sorted(ABBREVIATIONS.values()) == sorted(US_STATES)


def test_unknown_state():
    with pytest.raises(ValueError):
        parse_list("cal")
