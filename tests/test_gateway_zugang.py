import pytest

from custom_components.jarvis.gateway_zugang import NichtErlaubt, pruefe

ERLAUBT = [("GET", "/health"), ("GET", "/areas"), ("GET", "/entities"), ("GET", "/entities/sensor.test"),
           ("GET", "/history"), ("POST", "/call"), ("POST", "/call_many")]
VERBOTEN = [("GET", "/../../etc/passwd"), ("GET", "/entities/../health"), ("GET", "/entities/%2e%2e"), ("GET", "/entities/a%2fb"),
            ("GET", "/entities/sensor.test/extra"), ("DELETE", "/entities"), ("POST", "/entities"), ("GET", "/call"),
            ("GET", "/config"), ("GET", "/entities/a b"), ("GET", "/entities/a;b"), ("GET", "//entities"),
            ("GET", "/api/v1/entities"), ("GET", "/entities?x=1"), ("GET", "/entities/ä"), ("POST", "/call/../health"),
            ("GET", ""), ("GET", "/restart"), ("GET", "http://evil/entities"), ("GET", "/entities/.")]


@pytest.mark.parametrize("methode,pfad", ERLAUBT)
def test_erlaubt(methode, pfad):
    pruefe(methode, pfad)


@pytest.mark.parametrize("methode,pfad", VERBOTEN)
def test_verboten(methode, pfad):
    with pytest.raises(NichtErlaubt):
        pruefe(methode, pfad)
