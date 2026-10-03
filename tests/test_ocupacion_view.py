"""La vista de ocupación pinta cada cajón con los colores del estado."""

from unittest.mock import MagicMock

from parking_app.core import theme
from parking_app.models.cajon_estacionamiento import EstadoCajon
from parking_app.models.evento_ocupacion import EventoOcupacion
from parking_app.services.mqtt_service import EstadoConexion
from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel
from parking_app.views.ocupacion_view import OcupacionView


def _vista():
    vm = OcupacionViewModel(MagicMock(), MagicMock(), MagicMock(), MagicMock(), 60, MagicMock())
    vista = OcupacionView(vm)
    vista.montar()
    return vista, vm


def test_estado_inicial():
    vista, _ = _vista()
    assert vista.view.route == "/ocupacion"
    assert vista._subtitulo.value == "0 de 4 cajones libres"
    assert vista._pildora.texto == "Conectando…"
    assert all(t.color_acento == "#9ca3af" for t in vista._tarjetas)


def test_eventos_colorean_cada_cajon_como_el_mockup():
    vista, vm = _vista()
    vm._cambiar_estado(EstadoConexion.CONECTADO)
    for modulo, estado in enumerate(
        [EstadoCajon.LIBRE, EstadoCajon.OCUPADO, EstadoCajon.RESERVADO], start=1
    ):
        vm._recibir_evento(EventoOcupacion(id_modulo=modulo, estado=estado))

    acentos = [t.color_acento for t in vista._tarjetas]
    assert acentos == [
        theme.colores_estado(e).acento for e in ("libre", "ocupado", "reservado", "no conectado")
    ]
    assert [t._texto.value for t in vista._tarjetas] == [
        "Libre", "Ocupado", "Reservado", "No conectado",
    ]
    assert vista._subtitulo.value == "1 de 4 cajones libres"
    assert vista._pildora.texto == "En vivo"
    assert vista._pildora.control.bgcolor == theme.ALERTA_FONDO


def test_desmontar_no_cierra_la_conexion_compartida():
    vista, vm = _vista()
    vista.desmontar()
    vm._mqtt.desconectar.assert_not_called()
