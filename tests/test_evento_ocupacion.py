import pytest

from parking_app.core.theme import colores_estado
from parking_app.models.cajon_estacionamiento import EstadoCajon
from parking_app.models.evento_ocupacion import EventoOcupacion, PayloadInvalidoError


def test_payload_valido_mapea_modulo_a_etiqueta():
    evento = EventoOcupacion.from_payload(b'{"id_modulo": 2, "estado": "no conectado"}')

    assert evento.etiqueta_cajon == "C2"
    assert evento.estado is EstadoCajon.NO_CONECTADO
    assert evento.origen_evento == "mqtt"
    assert evento.marca_tiempo is not None


@pytest.mark.parametrize(
    "payload",
    [
        b"no es json",
        b"[]",
        b'{"estado": "libre"}',
        b'{"id_modulo": 5, "estado": "libre"}',
        b'{"id_modulo": "1", "estado": "libre"}',
        b'{"id_modulo": true, "estado": "libre"}',
        b'{"id_modulo": 1, "estado": "averiado"}',
        b"\xff\xfe",
    ],
)
def test_payload_invalido(payload):
    with pytest.raises(PayloadInvalidoError):
        EventoOcupacion.from_payload(payload)


def test_todos_los_estados_tienen_color():
    for estado in EstadoCajon:
        assert colores_estado(estado).acento.startswith("#")
