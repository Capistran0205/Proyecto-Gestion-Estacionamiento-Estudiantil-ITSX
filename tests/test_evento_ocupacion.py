import pytest

from parking_app.core.theme import colores_estado
from parking_app.models.cajon_estacionamiento import (
    EstadoCajon,
    EstadoSistema,
    estado_efectivo,
    sensor_de_estado_efectivo,
    sistema_de_estado_efectivo,
)
from parking_app.models.evento_ocupacion import EventoOcupacion, EventoSistema, PayloadInvalidoError


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
        # Reservado y bloqueado los decide el backend, no el sensor.
        b'{"id_modulo": 1, "estado": "reservado"}',
        b'{"id_modulo": 1, "estado": "bloqueado"}',
        b"\xff\xfe",
    ],
)
def test_payload_invalido(payload):
    with pytest.raises(PayloadInvalidoError):
        EventoOcupacion.from_payload(payload)


def test_todos_los_estados_tienen_color():
    for estado in EstadoCajon:
        assert colores_estado(estado).acento.startswith("#")
    assert colores_estado(EstadoCajon.BLOQUEADO).acento == "#FFCE1B"


def test_payload_del_sistema():
    evento = EventoSistema.from_payload(b'{"id_modulo": 3, "estado": "liberado"}')
    assert evento.etiqueta_cajon == "C3"
    assert evento.estado is EstadoSistema.LIBERADO
    with pytest.raises(PayloadInvalidoError):
        EventoSistema.from_payload(b'{"id_modulo": 3, "estado": "libre"}')


S, R, B, L = EstadoSistema.LIBERADO, EstadoSistema.RESERVADO, EstadoSistema.BLOQUEADO, EstadoCajon.LIBRE


@pytest.mark.parametrize(
    ("sensor", "sistema", "esperado"),
    [
        (EstadoCajon.NO_CONECTADO, R, EstadoCajon.NO_CONECTADO),
        (EstadoCajon.OCUPADO, R, EstadoCajon.OCUPADO),
        (EstadoCajon.OCUPADO, B, EstadoCajon.OCUPADO),
        (L, R, EstadoCajon.RESERVADO),
        (L, B, EstadoCajon.BLOQUEADO),
        (L, S, EstadoCajon.LIBRE),
    ],
)
def test_regla_de_estado_efectivo(sensor, sistema, esperado):
    assert estado_efectivo(sensor, sistema) is esperado


@pytest.mark.parametrize("estado", list(EstadoCajon))
def test_el_snapshot_se_reconstruye_sin_perder_el_estado(estado):
    sensor, sistema = sensor_de_estado_efectivo(estado), sistema_de_estado_efectivo(estado)
    assert estado_efectivo(sensor, sistema) is estado
