from gravelmaps import tags as T


def c(**kw):
    return T.classify({k.replace("__", ":").replace("_4wd", "4wd"): v for k, v in kw.items()})


def test_non_road_ignored():
    assert c(building="yes") is None
    assert c(highway="footway") is None
    assert c(highway="service", service="driveway") is None


def test_track_defaults_unpaved_and_legal():
    rc, surface, rough, legal, oneway = c(highway="track")
    assert rc == T.TRACK and surface == T.UNPAVED and legal == T.CAR | T.MOTO and oneway == 0


def test_surface_tags():
    assert c(highway="secondary", surface="gravel")[1] == T.UNPAVED
    assert c(highway="track", surface="asphalt")[1] == T.PAVED
    assert c(highway="unclassified")[1] == T.MAYBE_UNPAVED
    assert c(highway="residential")[1] == T.PAVED
    assert c(highway="track", tracktype="grade1")[1] == T.PAVED


def test_rough():
    assert c(highway="track", tracktype="grade5")[2] == 1
    assert T.classify({"highway": "track", "4wd_only": "yes"})[2] == 1
    assert c(highway="track", tracktype="grade2")[2] == 0


def test_private_and_closed():
    assert c(highway="track", access="private") is None
    assert c(highway="track", motor_vehicle="no") is None
    # motorcycles explicitly allowed on an otherwise closed track
    assert c(highway="track", motor_vehicle="no", motorcycle="yes")[3] == T.MOTO


def test_trails_need_explicit_motor_access():
    assert c(highway="path") is None
    assert c(highway="path", motorcycle="yes")[3] == T.MOTO
    assert c(highway="path", motor_vehicle="designated")[3] == T.MOTO | T.CAR
    assert c(highway="path", atv="yes")[3] == T.MOTO
    assert c(highway="path", atv="yes", motorcycle="no") is None


def test_oneway():
    assert c(highway="motorway")[4] == 1
    assert c(highway="primary", oneway="-1")[4] == -1
    assert c(highway="primary", junction="roundabout")[4] == 1


def test_barriers():
    b = T.barrier_blocks
    assert b({"barrier": "gate"}) == 0
    assert b({"barrier": "cattle_grid"}) == 0
    assert b({"barrier": "gate", "locked": "yes"}) == T.CAR | T.MOTO
    assert b({"barrier": "gate", "access": "private"}) == T.CAR | T.MOTO
    assert b({"barrier": "gate", "motor_vehicle": "no"}) == T.CAR | T.MOTO
    assert b({"barrier": "gate", "motorcar": "no"}) == T.CAR
    assert b({"barrier": "bollard"}) == T.CAR | T.MOTO
    assert b({"barrier": "bollard", "motorcycle": "yes"}) == T.CAR
    assert b({"barrier": "lift_gate", "access": "yes"}) == 0
    assert b({"barrier": "fence"}) == 0


def test_disused_and_permit_roads_excluded():
    assert c(highway="track", disused="yes") is None
    assert c(highway="track", access="permit") is None


def test_dualsport_extras():
    # OHV-open road closed to street vehicles
    assert c(highway="track", motor_vehicle="no", ohv="yes")[3] == T.MOTO
    # too narrow / impassable for a car
    assert c(highway="track", maxwidth="1.5")[3] == T.MOTO
    assert c(highway="track", maxwidth="5'")[3] == T.MOTO
    assert c(highway="track", smoothness="impassable")[3] == T.MOTO
    assert c(highway="track", maxwidth="3")[3] == T.CAR | T.MOTO
