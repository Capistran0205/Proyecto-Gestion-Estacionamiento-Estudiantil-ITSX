from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from parking_app.models.cajon_estacionamiento import EstadoCajon
from parking_app.services.cajones_service import CajonesNoDisponiblesError, CajonesService


def _servicio(filas=None, error=None):
    cliente = MagicMock()
    consulta = cliente.table.return_value.select.return_value.order.return_value
    if error:
        consulta.execute.side_effect = error
    else:
        consulta.execute.return_value = SimpleNamespace(data=filas)
    return CajonesService(cliente_factory=lambda: cliente), cliente


def test_devuelve_los_cuatro_cajones_en_orden():
    servicio, cliente = _servicio(
        [
            {"id_cajon": 1, "etiqueta": "C1", "estado_actual": "libre", "estado_actividad": True},
            {"id_cajon": 3, "etiqueta": "C3", "estado_actual": "ocupado", "estado_actividad": True},
            {"id_cajon": 4, "etiqueta": "C4", "estado_actual": "reservado",
             "estado_actividad": False},
        ]
    )

    cajones = servicio.obtener_estado_actual()

    cliente.table.assert_called_once_with("cajones")
    assert [c.etiqueta for c in cajones] == ["C1", "C2", "C3", "C4"]
    assert [c.estado_actual for c in cajones] == [
        EstadoCajon.LIBRE,
        EstadoCajon.NO_CONECTADO,  # sin fila
        EstadoCajon.OCUPADO,
        EstadoCajon.NO_CONECTADO,  # dado de baja
    ]


def test_fila_invalida_no_rompe_el_resto():
    servicio, _ = _servicio(
        [{"etiqueta": "C1"}, {"id_cajon": 2, "etiqueta": "C2", "estado_actual": "no_conectado"}]
    )
    cajones = servicio.obtener_estado_actual()
    assert len(cajones) == 4


def test_error_de_red():
    servicio, _ = _servicio(error=RuntimeError("timeout"))
    with pytest.raises(CajonesNoDisponiblesError):
        servicio.obtener_estado_actual()
