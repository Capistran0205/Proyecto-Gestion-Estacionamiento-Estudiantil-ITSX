"""Módulo C: reservas del administrador y escáner QR (ViewModels + Views)."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from parking_app.models.reserva_cajon import (
    EstadoReserva,
    LlegadaRegistrada,
    ReglasReserva,
    ReservaCajon,
)
from parking_app.services.reservas_service import ReservaError, ReservasNoDisponiblesError
from parking_app.viewmodels.admin_reservas_viewmodel import AdminReservasViewModel, FaseAdmin
from parking_app.viewmodels.escaner_viewmodel import EscanerViewModel, FaseEscaner
from parking_app.viewmodels.formato import id_corto
from parking_app.views.admin_reservas_view import AdminReservasView
from parking_app.views.escaner_view import EscanerView

AHORA = datetime.fromisoformat("2026-10-06T16:30:00+00:00")  # 10:30 en México
CODIGO = "5b1f6c1e2c1d4c399a516f0e8f2a3b4c"
ID = "5b1f6c1e-2c1d-4c39-9a51-6f0e8f2a3b4c"


def _reserva(etiqueta, estado=EstadoReserva.PENDIENTE_LLEGADA, cronometro_min=20, **extra):
    return ReservaCajon(
        id_reserva=f"id-{etiqueta}", id_cajon=int(etiqueta[1:]), codigo_qr="",
        estado=estado,
        fecha_inicio=datetime.fromisoformat("2026-10-06T17:00:00+00:00"),
        fecha_fin=datetime.fromisoformat("2026-10-06T20:00:00+00:00"),
        cronometro=AHORA + timedelta(minutes=cronometro_min) if cronometro_min is not None
        else None,
        etiqueta=etiqueta, **extra,
    )


POR_LLEGAR = _reserva("C1", cronometro_min=12.5)
EN_TOLERANCIA = _reserva("C3", cronometro_min=-5)  # pasó su hora hace 5 min
EN_USO = _reserva("C2", EstadoReserva.EN_USO, cronometro_min=None,
                  fecha_llegada=datetime.fromisoformat("2026-10-06T16:05:00+00:00"))


# --- Reservas del administrador ---

def _admin(reservas=(POR_LLEGAR, EN_TOLERANCIA, EN_USO), reglas=ReglasReserva(60, 20)):
    servicio = MagicMock()
    servicio.reservas_activas.return_value = list(reservas)
    servicio.reglas.return_value = reglas
    al_regresar, al_escanear = MagicMock(), MagicMock()
    vm = AdminReservasViewModel(servicio, al_regresar, al_escanear, reloj=lambda: AHORA)
    asyncio.run(vm.actualizar())
    return vm, servicio, al_regresar, al_escanear


def test_contadores_por_fase():
    vm, *_ = _admin()
    assert [vm.contar(f) for f in FaseAdmin] == [1, 1, 1]


def test_filas_como_el_mockup():
    vm, *_ = _admin()
    por_llegar, tolerancia, en_uso = vm.filas
    assert (por_llegar.etiqueta, por_llegar.titulo, por_llegar.detalle, por_llegar.tiempo) == (
        "C1", "Por llegar", "Reserva 11:00 a 14:00", "12:30")
    assert (tolerancia.titulo, tolerancia.detalle, tolerancia.tiempo) == (
        "En tolerancia", "Retraso · Reserva 11:00 a 14:00", "15:00")
    assert (en_uso.titulo, en_uso.detalle, en_uso.tiempo) == (
        "En uso", "Llegó a las 10:05 · Sale 14:00", "03:30")


def test_sin_reglas_la_tolerancia_no_se_inventa():
    servicio = MagicMock()
    servicio.reservas_activas.return_value = [EN_TOLERANCIA]
    servicio.reglas.side_effect = ReservasNoDisponiblesError("x")
    vm = AdminReservasViewModel(servicio, MagicMock(), MagicMock(), reloj=lambda: AHORA)
    asyncio.run(vm.actualizar())
    assert vm.filas[0].tiempo == "--:--"
    assert vm.alerta is None


def test_sin_reservas():
    vm, *_ = _admin(reservas=())
    assert vm.vacia


def test_error_al_cargar():
    servicio = MagicMock()
    servicio.reservas_activas.side_effect = ReservasNoDisponiblesError("x", sin_red=True)
    vm = AdminReservasViewModel(servicio, MagicMock(), MagicMock(), reloj=lambda: AHORA)
    asyncio.run(vm.actualizar())
    assert vm.alerta.titulo == "No se pudo conectar"


def test_boton_escanear():
    vm, _, _, al_escanear = _admin()
    asyncio.run(vm.escanear())
    al_escanear.assert_called_once()


def test_vista_reservas():
    vm, *_ = _admin()
    vista = AdminReservasView(vm)
    assert [c.numero.value for c in vista._contadores.values()] == ["1", "1", "1"]
    assert len(vista._lista.controls) == 3
    assert not vista._vacia.visible and not vista._cargando.visible


# --- Escáner ---

LLEGADA = LlegadaRegistrada(ID, 1, "C1", datetime.fromisoformat("2026-10-06T16:58:00+00:00"),
                            datetime.fromisoformat("2026-10-06T20:00:00+00:00"), "vehiculo",
                            "Ana Pérez")


def _escaner():
    servicio, lector = MagicMock(), MagicMock()
    servicio.confirmar_llegada.return_value = LLEGADA
    servicio.obtener_reserva.return_value = _reserva("C1")
    servicio.reglas.return_value = ReglasReserva(60, 20)
    lector.leer.return_value = CODIGO
    al_regresar, al_ver = MagicMock(), MagicMock()
    vm = EscanerViewModel(servicio, al_regresar, al_ver, lector=lector)
    return vm, servicio, lector, al_regresar, al_ver


def test_un_cuadro_con_qr_valida_y_registra_la_llegada():
    vm, servicio, *_ = _escaner()
    asyncio.run(vm.procesar_cuadro(b"jpeg"))
    servicio.confirmar_llegada.assert_called_once_with(CODIGO)
    r = vm.resultado
    assert vm.fase == FaseEscaner.RESULTADO and vm.titulo == "Resultado"
    assert (r.valido, r.titulo, r.subtitulo) == (
        True, "Código válido", "Se registró la llegada del estudiante.")
    assert r.cajon == ("C1", "Llegada registrada a las 10:58")
    assert r.filas == [
        ("Reserva", "#5B1F6C1E"),
        ("Horario reservado", "11:00 a 14:00"),
        ("Medio de transporte", "Automóvil"),
        ("Estado", "Cronómetro de uso iniciado"),
    ]


def test_cuadro_sin_qr_sigue_escaneando():
    vm, servicio, lector, *_ = _escaner()
    lector.leer.return_value = None
    asyncio.run(vm.procesar_cuadro(b"jpeg"))
    assert vm.fase == FaseEscaner.ESCANEANDO
    servicio.confirmar_llegada.assert_not_called()


def test_qr_ajeno_no_va_al_servidor():
    vm, servicio, lector, *_ = _escaner()
    lector.leer.return_value = "https://ejemplo.com"
    asyncio.run(vm.procesar_cuadro(b"jpeg"))
    servicio.confirmar_llegada.assert_not_called()
    assert vm.resultado.motivo[0] == "Código no reconocido"


@pytest.mark.parametrize(
    ("codigo", "reserva", "motivo", "ultima_fila"),
    [
        ("QR_EXPIRADO", _reserva("C3", EstadoReserva.EXPIRADA, cronometro_min=-30),
         "Código expirado", ("Expiró a las", "10:20")),
        ("QR_USADO", _reserva("C1", EstadoReserva.EN_USO, fecha_llegada=AHORA),
         "Código ya utilizado", ("Llegada registrada", "10:30")),
        ("QR_CANCELADO", _reserva("C1", EstadoReserva.CANCELADA),
         "Reserva cancelada", ("Horario reservado", "11:00 a 14:00")),
    ],
)
def test_rechazos_con_motivo_y_datos(codigo, reserva, motivo, ultima_fila):
    vm, servicio, *_ = _escaner()
    servicio.confirmar_llegada.side_effect = ReservaError(codigo, "x", 409)
    servicio.reserva_por_codigo.return_value = reserva
    asyncio.run(vm.validar(CODIGO))
    r = vm.resultado
    assert (r.valido, r.titulo, r.subtitulo) == (
        False, "Código rechazado", "No se registró ninguna llegada.")
    assert r.motivo[0] == motivo
    assert r.filas[:2] == [("Reserva", id_corto(reserva.id_reserva)),
                           ("Cajón", reserva.etiqueta)]
    assert r.filas[-1] == ultima_fila


def test_motivo_de_expiracion_usa_la_tolerancia_del_backend():
    vm, servicio, *_ = _escaner()
    servicio.confirmar_llegada.side_effect = ReservaError("QR_EXPIRADO", "x", 409)
    servicio.reserva_por_codigo.return_value = None
    asyncio.run(vm.validar(CODIGO))
    assert "tolerancia de 20 minutos" in vm.resultado.motivo[1]


def test_codigo_inexistente():
    vm, servicio, *_ = _escaner()
    servicio.confirmar_llegada.side_effect = ReservaError("QR_INVALIDO", "x", 404)
    asyncio.run(vm.validar(CODIGO))
    assert vm.resultado.motivo[0] == "Código no reconocido"
    servicio.reserva_por_codigo.assert_not_called()


def test_sin_conexion_pide_volver_a_escanear():
    vm, servicio, *_ = _escaner()
    servicio.confirmar_llegada.side_effect = ReservasNoDisponiblesError("x", sin_red=True)
    asyncio.run(vm.validar(CODIGO))
    assert vm.resultado.titulo == "No se pudo validar"
    assert "ya utilizado" in vm.resultado.motivo[1]


def test_cancelar_la_validacion_vuelve_a_escanear():
    vm, servicio, *_ = _escaner()

    def lento(_codigo):
        import time
        time.sleep(0.3)
        return LLEGADA

    servicio.confirmar_llegada.side_effect = lento

    async def escenario():
        tarea = asyncio.create_task(vm.validar(CODIGO))
        await asyncio.sleep(0.05)
        assert vm.fase == FaseEscaner.VALIDANDO
        vm.cancelar_validacion()
        await tarea
        assert vm.fase == FaseEscaner.ESCANEANDO and vm.resultado is None

    asyncio.run(escenario())


def test_escanear_otro_y_ver_reservas():
    vm, _, _, _, al_ver = _escaner()
    asyncio.run(vm.validar(CODIGO))
    vm.escanear_otro()
    assert vm.fase == FaseEscaner.ESCANEANDO and vm.resultado is None
    asyncio.run(vm.ver_reservas())
    al_ver.assert_called_once()


def test_linterna():
    vm, *_ = _escaner()
    vm.alternar_linterna()
    assert vm.linterna
    asyncio.run(vm.validar(CODIGO))
    assert not vm.linterna  # se apaga al validar


def test_vista_escaner_en_la_pc_y_resultados():
    vm, servicio, *_ = _escaner()
    vista = EscanerView(vm, con_camara=False)
    assert vista._manual.visible and not vista._linterna.visible
    assert vista._titulo.value == "Escanear QR"

    vista._codigo_manual.campo.value = CODIGO
    asyncio.run(vista._on_validar_manual(None))
    vista._render()
    assert vista._resultado.visible and vista._titulo.value == "Resultado"
    assert len(vista._contenido_resultado.controls) == 6  # círculo, títulos, cajón, tabla

    vm.escanear_otro()
    servicio.confirmar_llegada.side_effect = ReservaError("QR_USADO", "x", 409)
    servicio.reserva_por_codigo.return_value = replace(_reserva("C1"), fecha_llegada=AHORA)
    asyncio.run(vm.validar(CODIGO))
    vista._render()
    assert vista._resultado.visible
    assert len(vista._contenido_resultado.controls) == 6  # círculo, títulos, motivo, tabla


# --- Consultas al ritmo de MQTT (menos peticiones y logs) ---

def test_la_lista_se_actualiza_cuando_mqtt_cambia_un_cajon():
    from parking_app.models.cajon_estacionamiento import EstadoSistema
    from parking_app.models.evento_ocupacion import EventoOcupacion, EventoSistema
    from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel

    async def escenario():
        ocupacion = OcupacionViewModel(MagicMock(), MagicMock(), MagicMock(), MagicMock(), 60,
                                       MagicMock())
        for modulo in range(1, 5):
            ocupacion._recibir_evento(EventoOcupacion(id_modulo=modulo, estado="libre"))
        servicio = MagicMock()
        servicio.reservas_activas.return_value = []
        servicio.reglas.return_value = ReglasReserva(60, 20)
        vm = AdminReservasViewModel(servicio, MagicMock(), MagicMock(), reloj=lambda: AHORA,
                                    ocupacion=ocupacion)
        await vm.iniciar()
        assert servicio.reservas_activas.call_count == 1

        ocupacion.notify_listeners()  # tic del reloj: sin cambio, no consulta
        await asyncio.sleep(0.05)
        assert servicio.reservas_activas.call_count == 1

        ocupacion._recibir_sistema(EventoSistema(id_modulo=2, estado=EstadoSistema.RESERVADO))
        await asyncio.sleep(0.05)
        assert servicio.reservas_activas.call_count == 2

        vm.liberar()
        ocupacion._recibir_sistema(EventoSistema(id_modulo=2, estado=EstadoSistema.LIBERADO))
        await asyncio.sleep(0.05)
        assert servicio.reservas_activas.call_count == 2  # ya no escucha

    asyncio.run(escenario())


def test_la_lista_se_actualiza_al_confirmar_la_salida_con_el_vehiculo_dentro():
    """La salida no cambia el estado del cajón (sigue ocupado y "liberado"), pero el
    backend publica en reserva1: eso basta para que la lista se entere."""
    from parking_app.models.cajon_estacionamiento import EstadoSistema
    from parking_app.models.evento_ocupacion import EventoOcupacion, EventoSistema
    from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel

    async def escenario():
        ocupacion = OcupacionViewModel(MagicMock(), MagicMock(), MagicMock(), MagicMock(), 60,
                                       MagicMock())
        ocupacion._recibir_evento(EventoOcupacion(id_modulo=1, estado="ocupado"))
        ocupacion._recibir_sistema(EventoSistema(id_modulo=1, estado=EstadoSistema.LIBERADO))
        servicio = MagicMock()
        servicio.reservas_activas.return_value = []
        servicio.reglas.return_value = ReglasReserva(60, 20)
        vm = AdminReservasViewModel(servicio, MagicMock(), MagicMock(), reloj=lambda: AHORA,
                                    ocupacion=ocupacion)
        await vm.iniciar()
        consultas = servicio.reservas_activas.call_count
        estado_antes = [c.estado for c in ocupacion.cajones]

        # confirmar-salida: el backend vuelve a publicar "liberado" en reserva1/1
        ocupacion._recibir_sistema(EventoSistema(id_modulo=1, estado=EstadoSistema.LIBERADO))
        await asyncio.sleep(0.05)
        assert [c.estado for c in ocupacion.cajones] == estado_antes
        assert servicio.reservas_activas.call_count == consultas + 1
        vm.liberar()

    asyncio.run(escenario())
