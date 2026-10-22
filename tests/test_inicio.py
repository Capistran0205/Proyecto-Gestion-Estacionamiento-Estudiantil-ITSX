import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from parking_app.core import theme
from parking_app.models.cajon_estacionamiento import EstadoCajon, EstadoSistema
from parking_app.models.evento_ocupacion import EventoOcupacion, EventoSistema
from parking_app.models.reserva_cajon import EstadoReserva, ReservaCajon
from parking_app.models.usuario import MedioTransporte, Rol, Usuario
from parking_app.services.mqtt_service import EstadoConexion
from parking_app.services.reservas_service import ReservasNoDisponiblesError
from parking_app.viewmodels.inicio_viewmodel import InicioViewModel, TarjetaReserva
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

    _eventos(ocupacion, EstadoCajon.OCUPADO, EstadoCajon.LIBRE, EstadoCajon.LIBRE)
    ocupacion._recibir_sistema(EventoSistema(id_modulo=2, estado=EstadoSistema.RESERVADO))
    # C4 sigue "no conectado": no cuenta en el porcentaje.
    assert (ocupacion.libres, ocupacion.ocupados, ocupacion.reservados) == (1, 1, 1)
    assert ocupacion.porcentaje_ocupado == 67
    assert ocupacion.texto_disponibilidad == "Disponibilidad media — 67% ocupado"

    ocupacion._recibir_sistema(EventoSistema(id_modulo=2, estado=EstadoSistema.LIBERADO))
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


# --- Tarjeta "Mi reserva" (mockup del menú del estudiante) ---

INICIO_RESERVA = datetime.fromisoformat("2026-10-06T17:00:00+00:00")
PENDIENTE = ReservaCajon(
    id_reserva="r1", id_cajon=1, codigo_qr="a" * 32, estado=EstadoReserva.PENDIENTE_LLEGADA,
    fecha_inicio=INICIO_RESERVA, fecha_fin=INICIO_RESERVA + timedelta(hours=3),
    cronometro=INICIO_RESERVA, etiqueta="C1",
)
EN_USO = replace(PENDIENTE, estado=EstadoReserva.EN_USO, cronometro=None)


def _vm_con_reserva(servidor, local=None, usuario=USUARIO):
    auth, reservas, almacen = MagicMock(), MagicMock(), MagicMock()
    auth.usuario_actual = usuario
    reservas.reserva_vigente.return_value = servidor
    almacen.leer.return_value = local
    al_mi_reserva = MagicMock()
    vm = InicioViewModel(auth, _ocupacion(), MagicMock(), MagicMock(), reservas_service=reservas,
                         almacen=almacen, al_ir_a_mi_reserva=al_mi_reserva)
    return vm, reservas, almacen, al_mi_reserva


def test_sin_reserva_no_hay_tarjeta():
    vm, *_ = _vm_con_reserva(None)
    asyncio.run(vm.actualizar_reserva())
    assert vm.tarjeta_reserva is None
    assert not InicioView(vm)._mi_reserva.control.visible


def test_tarjeta_antes_de_la_llegada():
    vm, *_ = _vm_con_reserva(PENDIENTE)
    asyncio.run(vm.actualizar_reserva())
    assert vm.tarjeta_reserva == TarjetaReserva("Código QR y tiempo de tu reserva", False)
    vista = InicioView(vm)
    assert vista._mi_reserva.control.visible and not vista._mi_reserva.insignia.visible


def test_tarjeta_en_uso_con_hora_de_fin():
    vm, _, _, al_mi_reserva = _vm_con_reserva(EN_USO)
    asyncio.run(vm.actualizar_reserva())
    assert vm.tarjeta_reserva == TarjetaReserva("Cajón C1 · termina a las 14:00", True)
    assert InicioView(vm)._mi_reserva.insignia.visible
    asyncio.run(vm.ir_a_mi_reserva())
    al_mi_reserva.assert_called_once()


def test_sin_red_muestra_la_copia_local():
    vm, reservas, almacen, _ = _vm_con_reserva(None, local=PENDIENTE)
    reservas.reserva_vigente.side_effect = ReservasNoDisponiblesError("sin red", sin_red=True)
    asyncio.run(vm.actualizar_reserva())
    assert vm.tarjeta_reserva is not None
    almacen.borrar.assert_not_called()


def test_reserva_terminada_borra_la_copia_local():
    vm, _, almacen, _ = _vm_con_reserva(None, local=EN_USO)
    asyncio.run(vm.actualizar_reserva())
    assert vm.tarjeta_reserva is None
    almacen.borrar.assert_called_once()


def test_el_administrador_no_ve_la_tarjeta():
    admin = replace(USUARIO, rol=Rol.ADMINISTRADOR)
    vm, reservas, *_ = _vm_con_reserva(PENDIENTE, usuario=admin)
    asyncio.run(vm.actualizar_reserva())
    reservas.reserva_vigente.assert_not_called()
    assert vm.tarjeta_reserva is None


def test_tarjeta_se_actualiza_cuando_mqtt_cambia_su_cajon():
    async def escenario():
        vm, reservas, *_ = _vm_con_reserva(PENDIENTE)
        _eventos(vm.ocupacion, *["libre"] * 4)
        await vm.iniciar()
        llamadas = reservas.reserva_vigente.call_count
        reservas.reserva_vigente.return_value = EN_USO

        vm.ocupacion._recibir_sistema(EventoSistema(id_modulo=3, estado=EstadoSistema.RESERVADO))
        await asyncio.sleep(0.05)
        assert reservas.reserva_vigente.call_count == llamadas  # otro cajón

        vm.ocupacion._recibir_evento(EventoOcupacion(id_modulo=1, estado="ocupado"))
        await asyncio.sleep(0.05)
        assert reservas.reserva_vigente.call_count == llamadas + 1
        assert vm.tarjeta_reserva.en_uso
        vm.liberar()

    asyncio.run(escenario())
