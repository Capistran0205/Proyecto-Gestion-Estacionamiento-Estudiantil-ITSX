"""Módulo B: Reservar cajón (ViewModel + View)."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from parking_app.models.cajon_estacionamiento import EstadoCajon, EstadoSistema
from parking_app.models.evento_ocupacion import EventoOcupacion, EventoSistema
from parking_app.models.reserva_cajon import BloqueoCajon, ReservaCajon
from parking_app.models.usuario import MedioTransporte, Usuario
from parking_app.services.reservas_service import ReservaError, ReservasNoDisponiblesError
from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel
from parking_app.viewmodels.reservar_viewmodel import PasoReserva, ReservarViewModel
from parking_app.views.reservar_view import ReservarView

# 11:00 a 22:00 hora de México (UTC-6).
INICIO = datetime.fromisoformat("2026-10-06T17:00:00+00:00")


def _bloqueo(etiqueta="C1", id_cajon=1, reglas=True):
    return BloqueoCajon(
        id_cajon=id_cajon,
        etiqueta=etiqueta,
        fecha_inicio=INICIO,
        fin_minimo=datetime.fromisoformat("2026-10-06T18:00:00+00:00"),
        fin_maximo=datetime.fromisoformat("2026-10-07T04:00:00+00:00"),
        bloqueado_hasta=datetime.fromisoformat("2026-10-06T16:22:00+00:00"),
        minutos_llegada=60 if reglas else None,
        minutos_tolerancia=20 if reglas else None,
    )


RESERVA = ReservaCajon.from_dict({
    "id_reserva": "r1", "codigo_qr": "a" * 32, "estado": "pendiente_llegada", "id_cajon": 1,
    "fecha_inicio": "2026-10-06T17:00:00+00:00", "fecha_fin": "2026-10-06T20:00:00+00:00",
})


def _ocupacion(*estados):
    ocupacion = OcupacionViewModel(MagicMock(), MagicMock(), MagicMock(), MagicMock(), 60,
                                   MagicMock())
    for modulo, estado in enumerate(estados or [EstadoCajon.LIBRE] * 4, start=1):
        ocupacion._recibir_evento(EventoOcupacion(id_modulo=modulo, estado=estado))
    return ocupacion


def _vm(ocupacion=None, etiqueta_inicial=None, ver_reserva=None):
    auth, reservas, almacen = MagicMock(), MagicMock(), MagicMock()
    auth.usuario_actual = Usuario("uid", "Ana", "Pérez", None, "ana@itsx.edu.mx",
                                  MedioTransporte.VEHICULO)
    reservas.bloquear_cajon.side_effect = lambda id_cajon: _bloqueo(f"C{id_cajon}", id_cajon)
    reservas.crear_reserva.return_value = RESERVA
    almacen.leer.return_value = None
    al_salir, al_creada = MagicMock(), MagicMock()
    vm = ReservarViewModel(
        auth, ocupacion or _ocupacion(), reservas, almacen,
        al_salir=al_salir, al_reserva_creada=al_creada, al_ver_reserva=ver_reserva,
        etiqueta_inicial=etiqueta_inicial,
    )
    return vm, reservas, almacen, al_salir, al_creada


def _correr(corutina_factory):
    async def escenario():
        await corutina_factory()
        await asyncio.sleep(0.05)  # deja terminar las liberaciones en segundo plano

    asyncio.run(escenario())


# --- Paso 1 ---

def test_tocar_un_cajon_en_el_mapa_lo_aparta_al_entrar():
    async def escenario():
        vm, reservas, *_ = _vm(etiqueta_inicial="C3")
        await vm.iniciar()
        reservas.bloquear_cajon.assert_called_once_with(3)
        assert vm.etiqueta == "C3"
        c3 = vm.cajones[2]
        assert (c3.estado, c3.texto_estado, c3.seleccionado) == (EstadoCajon.BLOQUEADO, "Bloqueado", True)
        assert vm.subtitulo_cajon == "Seleccionado para reservar"

    _correr(escenario)


def test_solo_los_cajones_libres_se_pueden_tocar():
    async def escenario():
        vm, reservas, *_ = _vm(_ocupacion(EstadoCajon.LIBRE, EstadoCajon.OCUPADO,
                                          EstadoCajon.LIBRE, EstadoCajon.NO_CONECTADO))
        await vm.iniciar()
        assert [c.tocable for c in vm.cajones] == [True, False, True, False]
        await vm.seleccionar("C2")
        reservas.bloquear_cajon.assert_not_called()

    _correr(escenario)


def test_cajon_apartado_por_otro_se_ve_bloqueado_y_no_se_toca():
    ocupacion = _ocupacion()
    ocupacion._recibir_sistema(EventoSistema(id_modulo=2, estado=EstadoSistema.BLOQUEADO))
    vm, *_ = _vm(ocupacion)
    c2 = vm.cajones[1]
    assert (c2.estado, c2.tocable, c2.seleccionado) == (EstadoCajon.BLOQUEADO, False, False)


def test_continuar_sin_cajon_pide_elegir_uno():
    vm, *_ = _vm()
    asyncio.run(vm.continuar())
    assert vm.paso == PasoReserva.ELEGIR
    assert vm.alerta.titulo == "Elige un cajón libre"


def test_rechazo_al_apartar_muestra_el_motivo():
    async def escenario():
        vm, reservas, *_ = _vm()
        reservas.bloquear_cajon.side_effect = ReservaError(
            "CAJON_BLOQUEADO", "Otro estudiante está reservando este cajón en este momento.", 409)
        await vm.seleccionar("C1")
        assert vm.alerta.titulo == "No se pudo apartar el cajón"
        assert vm.alerta.detalle.startswith("Otro estudiante")
        assert vm.etiqueta is None

    _correr(escenario)


def test_con_reserva_activa_se_muestra_el_aviso():
    async def escenario():
        vm, reservas, *_ = _vm(etiqueta_inicial="C1")
        reservas.bloquear_cajon.side_effect = ReservaError("RESERVA_ACTIVA", "Ya tienes una reserva activa.")
        await vm.iniciar()
        assert vm.tiene_reserva_activa
        assert not vm.puede_ver_reserva  # sin pantalla de la reserva (el router sí la pasa)

    _correr(escenario)


def test_reserva_guardada_en_el_telefono_no_va_a_la_red():
    # Sin internet el estudiante igual llega a "Ver mi reserva" (RNF-08).
    async def escenario():
        vm, reservas, almacen, *_ = _vm(etiqueta_inicial="C1", ver_reserva=MagicMock())
        limite = datetime.now(UTC) + timedelta(minutes=30)
        almacen.leer.return_value = replace(RESERVA, cronometro=limite, minutos_tolerancia=20)
        await vm.iniciar()
        assert vm.tiene_reserva_activa and vm.puede_ver_reserva
        reservas.bloquear_cajon.assert_not_called()

    _correr(escenario)


def test_reserva_guardada_con_tolerancia_vencida_se_ignora():
    async def escenario():
        vm, reservas, almacen, *_ = _vm(etiqueta_inicial="C1")
        vencida = datetime.now(UTC) - timedelta(minutes=30)
        almacen.leer.return_value = replace(RESERVA, cronometro=vencida, minutos_tolerancia=20)
        await vm.iniciar()
        reservas.bloquear_cajon.assert_called_once_with(1)

    _correr(escenario)


def test_sin_conexion_al_apartar():
    async def escenario():
        vm, reservas, *_ = _vm()
        reservas.bloquear_cajon.side_effect = ReservasNoDisponiblesError("x", sin_red=True)
        await vm.seleccionar("C1")
        assert vm.alerta.titulo == "No se pudo conectar"
        assert not vm.cargando

    _correr(escenario)


def test_servicio_caido_no_culpa_a_la_conexion_del_estudiante():
    # P. ej. la función no está desplegada (404) o falla en el servidor (5xx).
    async def escenario():
        vm, reservas, *_ = _vm()
        reservas.bloquear_cajon.side_effect = ReservasNoDisponiblesError("HTTP 404")
        await vm.seleccionar("C1")
        assert vm.alerta.titulo == "El servicio de reservas no está disponible"

    _correr(escenario)


# --- Paso 2 ---

def test_horario_con_opciones_validas_y_duracion():
    async def escenario():
        vm, *_ = _vm(etiqueta_inicial="C1")
        await vm.iniciar()
        await vm.continuar()
        assert vm.paso == PasoReserva.HORARIO
        assert vm.subtitulo_cajon == "Apartado para ti mientras completas la reserva"
        assert vm.hora_inicio == "11:00"
        horas = [texto for _, texto in vm.opciones_fin]
        assert horas[0] == "12:00" and horas[-1] == "22:00" and len(horas) == 11
        assert vm.duracion == "1 h"  # por omisión, la mínima

        vm.set_fin(vm.opciones_fin[2][0])
        assert vm.duracion == "3 h"

    _correr(escenario)


# --- Paso 3 ---

def test_resumen_y_avisos_con_las_reglas_del_backend():
    async def escenario():
        vm, *_ = _vm(etiqueta_inicial="C1")
        await vm.iniciar()
        await vm.continuar()
        vm.set_fin(vm.opciones_fin[2][0])
        await vm.continuar()
        assert vm.paso == PasoReserva.CONFIRMAR
        assert dict(vm.resumen) == {
            "Cajón": "C1", "Fecha": "06/10/2026", "Hora de inicio": "11:00",
            "Hora de fin": "14:00", "Duración": "3 h", "Medio de transporte": "Automóvil",
        }
        primero = vm.avisos[0]
        assert [t for t, negritas in primero if negritas] == ["1 hora", "20 minutos"]

    _correr(escenario)


def test_avisos_sin_reglas_no_inventan_valores():
    async def escenario():
        vm, reservas, *_ = _vm(etiqueta_inicial="C1")
        reservas.bloquear_cajon.side_effect = lambda i: _bloqueo(reglas=False)
        await vm.iniciar()
        texto = "".join(t for t, _ in vm.avisos[0])
        assert "hora" not in texto and "minutos" not in texto

    _correr(escenario)


def test_confirmar_crea_la_reserva_y_la_guarda_en_el_telefono():
    async def escenario():
        vm, reservas, almacen, al_salir, al_creada = _vm(etiqueta_inicial="C1")
        await vm.iniciar()
        await vm.continuar()
        vm.set_fin(vm.opciones_fin[2][0])
        await vm.continuar()
        await vm.confirmar()
        reservas.crear_reserva.assert_called_once_with(
            1, INICIO, datetime.fromisoformat("2026-10-06T20:00:00+00:00"))
        # Se guarda con la etiqueta y la tolerancia del bloqueo (para "Mi reserva").
        almacen.guardar.assert_called_once_with(
            "uid", replace(RESERVA, etiqueta="C1", minutos_tolerancia=20))
        al_creada.assert_called_once()
        # El backend ya consumió el bloqueo: salir no lo libera.
        vm.liberar()
        reservas.liberar_bloqueo.assert_not_called()

    _correr(escenario)


@pytest.mark.parametrize(
    ("codigo", "error_campo"),
    [("FUERA_DE_HORARIO", "Fuera del horario de operación"),
     ("DURACION_EXCEDIDA", "Excede la duración máxima")],
)
def test_rechazo_de_horario_vuelve_al_paso_2(codigo, error_campo):
    async def escenario():
        vm, reservas, *_ = _vm(etiqueta_inicial="C1")
        reservas.crear_reserva.side_effect = ReservaError(codigo, "Mensaje de la base.", 422)
        await vm.iniciar()
        await vm.continuar()
        await vm.continuar()
        await vm.confirmar()
        assert vm.paso == PasoReserva.HORARIO
        assert vm.alerta.titulo == "No se puede reservar en este horario"
        assert vm.alerta.detalle == "Mensaje de la base."
        assert vm.error_fin == error_campo
        assert vm.etiqueta == "C1"  # el cajón sigue apartado

    _correr(escenario)


def test_bloqueo_vencido_vuelve_al_paso_1_sin_cajon():
    async def escenario():
        vm, reservas, *_ = _vm(etiqueta_inicial="C1")
        reservas.crear_reserva.side_effect = ReservaError("BLOQUEO_EXPIRADO", "Se agotó el tiempo.")
        await vm.iniciar()
        await vm.continuar()
        await vm.continuar()
        await vm.confirmar()
        assert vm.paso == PasoReserva.ELEGIR
        assert vm.etiqueta is None
        assert vm.alerta.titulo == "Se agotó el tiempo para reservar"

    _correr(escenario)


# --- Salir / regresar ---

def test_cancelar_libera_el_cajon_y_sale():
    async def escenario():
        vm, reservas, _, al_salir, _ = _vm(etiqueta_inicial="C1")
        await vm.iniciar()
        await vm.continuar()
        await vm.cancelar()
        await asyncio.sleep(0.05)
        reservas.liberar_bloqueo.assert_called_once_with(1)
        al_salir.assert_called_once()

    _correr(escenario)


def test_regresar_entre_pasos_conserva_el_cajon():
    async def escenario():
        vm, reservas, _, al_salir, _ = _vm(etiqueta_inicial="C1")
        await vm.iniciar()
        await vm.continuar()
        await vm.continuar()
        await vm.regresar()
        assert vm.paso == PasoReserva.HORARIO
        await vm.regresar()
        assert vm.paso == PasoReserva.ELEGIR and vm.etiqueta == "C1"
        reservas.liberar_bloqueo.assert_not_called()
        await vm.regresar()  # desde el paso 1: sale y libera
        await asyncio.sleep(0.05)
        reservas.liberar_bloqueo.assert_called_once_with(1)
        al_salir.assert_called_once()

    _correr(escenario)


def test_salir_de_la_pantalla_libera_el_cajon():
    async def escenario():
        vm, reservas, *_ = _vm(etiqueta_inicial="C1")
        await vm.iniciar()
        vm.liberar()
        await asyncio.sleep(0.05)
        reservas.liberar_bloqueo.assert_called_once_with(1)

    _correr(escenario)


# --- View ---

def test_vista_paso_1_como_el_mockup():
    async def escenario():
        ocupacion = _ocupacion(EstadoCajon.LIBRE, EstadoCajon.OCUPADO, EstadoCajon.LIBRE,
                               EstadoCajon.NO_CONECTADO)
        vm, *_ = _vm(ocupacion, etiqueta_inicial="C1")
        vista = ReservarView(vm)
        vista.montar()
        await vm.iniciar()

        assert vista._progreso.texto == "Paso 1 de 3"
        c1, c2, c3, c4 = vista._tarjetas
        assert c1.seleccionada and c1.color_acento == "#FFCE1B"
        assert c1._tarjeta.bgcolor == "#413817"
        assert c2._tarjeta.opacity < 1 and c4._tarjeta.opacity < 1
        assert c3._tarjeta.opacity == 1 and c3._tarjeta.on_click is not None
        assert vista._recuadro_1.titulo == "Cajón C1"
        assert not vista._cancelar.visible
        vista.desmontar()

    _correr(escenario)


def test_vista_pasos_2_y_3():
    async def escenario():
        vm, reservas, *_ = _vm(etiqueta_inicial="C1")
        vista = ReservarView(vm)
        vista.montar()
        await vm.iniciar()
        await vm.continuar()
        assert vista._paso_2.visible and vista._progreso.texto == "Paso 2 de 3"
        assert vista._inicio.campo.value == "11:00"
        assert len(vista._fin.options) == 11
        assert vista._duracion.value == "1 h"

        await vm.continuar()
        assert vista._paso_3.visible
        assert [f.valor.value for f in vista._filas_resumen][0] == "C1"
        assert vista._continuar.content == "Confirmar reserva"

        reservas.crear_reserva.side_effect = ReservaError("FUERA_DE_HORARIO", "Fuera.", 422)
        await vm.confirmar()
        assert vista._paso_2.visible
        assert vista._banner_2.titulo == "No se puede reservar en este horario"
        assert vista._error_fin.texto == "Fuera del horario de operación"
        vista.desmontar()

    _correr(escenario)


def test_vista_reserva_activa():
    async def escenario():
        vm, reservas, *_ = _vm(etiqueta_inicial="C1")
        reservas.bloquear_cajon.side_effect = ReservaError("RESERVA_ACTIVA", "x")
        vista = ReservarView(vm)
        vista.montar()
        await vm.iniciar()
        assert vista._reserva_activa.visible and not vista._flujo.visible
        assert not vista._ver_reserva.visible
        vista.desmontar()

    _correr(escenario)


# --- Ocupación: tocar un cajón libre ---

def test_en_ocupacion_solo_un_cajon_libre_abre_la_reserva():
    al_reservar = MagicMock()
    ocupacion = OcupacionViewModel(MagicMock(), MagicMock(), MagicMock(), MagicMock(), 60,
                                   MagicMock(), al_reservar=al_reservar)
    for modulo, estado in enumerate([EstadoCajon.LIBRE, EstadoCajon.OCUPADO], start=1):
        ocupacion._recibir_evento(EventoOcupacion(id_modulo=modulo, estado=estado))

    asyncio.run(ocupacion.reservar("C2"))
    al_reservar.assert_not_called()
    asyncio.run(ocupacion.reservar("C1"))
    al_reservar.assert_called_once_with("C1")
