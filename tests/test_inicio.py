import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from parking_app.core import theme
from parking_app.models.cajon_estacionamiento import EstadoCajon
from parking_app.models.evento_ocupacion import EventoOcupacion
from parking_app.models.usuario import MedioTransporte, Usuario
from parking_app.services.mqtt_service import EstadoConexion
from parking_app.viewmodels.inicio_viewmodel import InicioViewModel
from parking_app.viewmodels.ocupacion_viewmodel import NivelDisponibilidad, OcupacionViewModel
from parking_app.views.inicio_view import InicioView

USUARIO = Usuario(
    "uid", "Ana Sofía", "Pérez", "López", "237o00526@itsx.edu.mx", MedioTransporte.VEHICULO
)


def _ocupacion():
    return OcupacionViewModel(MagicMock(), MagicMock(), MagicMock(), MagicMock(), 60, MagicMock())


def _vm(usuario=USUARIO, hora=9):
    auth = MagicMock()
    auth.usuario_actual = usuario
    auth.correo_actual = "237o00526@itsx.edu.mx"
    # La contraseña MQTT ya se descartó al conectar: el correo no depende de ella.
    auth.credenciales_mqtt = None
    navegar_ocupacion, navegar_login = MagicMock(), MagicMock()
    vm = InicioViewModel(
        auth, _ocupacion(), navegar_ocupacion, navegar_login,
        ahora=lambda: datetime(2026, 9, 26, hora),
    )
    return vm, auth, navegar_ocupacion, navegar_login


def _eventos(ocupacion, *estados):
    for modulo, estado in enumerate(estados, start=1):
        ocupacion._recibir_evento(EventoOcupacion(id_modulo=modulo, estado=estado))


@pytest.mark.parametrize(
    ("hora", "saludo"), [(9, "Buenos días"), (15, "Buenas tardes"), (21, "Buenas noches"),
                         (3, "Buenas noches")]
)
def test_saludo_segun_la_hora(hora, saludo):
    vm, _, _, _ = _vm(hora=hora)
    assert vm.saludo == saludo


def test_datos_del_estudiante_para_el_menu():
    vm, _, _, _ = _vm()
    assert vm.nombre_corto == "Ana Sofía Pérez"
    assert vm.nombre_completo == "Ana Sofía Pérez López"
    assert vm.numero_control == "237O00526"
    assert vm.correo == "237o00526@itsx.edu.mx"
    assert vm.iniciales == "AP"


def test_sin_perfil_usa_el_correo():
    vm, _, _, _ = _vm(usuario=None)
    assert vm.nombre_corto == "Estudiante"
    assert vm.numero_control == "237O00526"
    assert vm.iniciales == "2"


def test_cerrar_sesion_navega_al_login():
    vm, auth, _, navegar_login = _vm()

    asyncio.run(vm.cerrar_sesion())

    auth.cerrar_sesion.assert_called_once()
    navegar_login.assert_called_once()
    assert not vm.cerrando_sesion


def test_cerrar_sesion_aun_con_error_remoto():
    vm, auth, _, navegar_login = _vm()
    auth.cerrar_sesion.side_effect = RuntimeError("sin red")

    asyncio.run(vm.cerrar_sesion())

    navegar_login.assert_called_once()


def test_disponibilidad():
    ocupacion = _ocupacion()
    assert ocupacion.nivel_disponibilidad is NivelDisponibilidad.SIN_DATOS
    assert ocupacion.texto_disponibilidad == "Sin datos de los sensores"

    _eventos(ocupacion, EstadoCajon.OCUPADO, EstadoCajon.RESERVADO, EstadoCajon.LIBRE)
    # C4 sigue "no conectado": no cuenta en el porcentaje.
    assert (ocupacion.libres, ocupacion.ocupados, ocupacion.reservados) == (1, 1, 1)
    assert ocupacion.porcentaje_ocupado == 67
    assert ocupacion.texto_disponibilidad == "Disponibilidad media — 67% ocupado"

    _eventos(ocupacion, EstadoCajon.LIBRE, EstadoCajon.LIBRE, EstadoCajon.LIBRE,
             EstadoCajon.OCUPADO)
    assert ocupacion.nivel_disponibilidad is NivelDisponibilidad.ALTA

    _eventos(ocupacion, *[EstadoCajon.OCUPADO] * 4)
    assert ocupacion.nivel_disponibilidad is NivelDisponibilidad.LLENO


def test_vista_refleja_estado_en_vivo():
    vm, _, _, _ = _vm()
    vista = InicioView(vm)
    vista.montar()

    vm.ocupacion._cambiar_estado(EstadoConexion.CONECTADO)
    _eventos(vm.ocupacion, EstadoCajon.LIBRE, EstadoCajon.OCUPADO, EstadoCajon.OCUPADO,
             EstadoCajon.LIBRE)

    assert vista._saludo.value == "Buenos días"
    assert vista._nombre.value == "Ana Sofía Pérez"
    assert vista._libres.value == "2"
    assert vista._total.value == "/ 4 cajones libres"
    assert vista._barra.value == 0.5
    assert vista._barra.color == theme.NARANJA
    assert vista._texto_nivel.value == "Disponibilidad media — 50% ocupado"
    assert [c.numero.value for c in vista._contadores.values()] == ["2", "2", "0"]
    assert vista._pildora.texto == "En vivo"
    assert vista.view.end_drawer is vista._menu.control
    assert vista._menu._numero_control.value == "237O00526"

    vista.desmontar()
    vm.ocupacion._recibir_evento(EventoOcupacion(id_modulo=1, estado=EstadoCajon.OCUPADO))
    assert vista._libres.value == "2"  # ya no escucha
