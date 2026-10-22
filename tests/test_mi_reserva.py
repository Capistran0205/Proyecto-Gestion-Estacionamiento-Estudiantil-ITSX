"""Módulo B, paso 3: "Mi reserva" (QR, cuenta regresiva, cancelar, extender, salida)."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import flet as ft
import pytest

from parking_app.models.reserva_cajon import EstadoReserva, ReglasReserva, ReservaCajon
from parking_app.models.usuario import MedioTransporte, Usuario
from parking_app.services.reservas_service import ReservaError, ReservasNoDisponiblesError
from parking_app.viewmodels.mi_reserva_viewmodel import (
    Confirmacion,
    FaseReserva,
    MiReservaViewModel,
    PantallaReserva,
    _cuenta_regresiva,
)
from parking_app.views.mi_reserva_view import MiReservaView

# Confirmada a las 10:00 (México): llegar antes de las 11:00, tolerancia hasta 11:20.
CONFIRMADA = datetime.fromisoformat("2026-10-06T16:00:00+00:00")
CRONOMETRO = CONFIRMADA + timedelta(hours=1)

RESERVA = ReservaCajon(
    id_reserva="r1",
    id_cajon=1,
    codigo_qr="a" * 32,
    estado=EstadoReserva.PENDIENTE_LLEGADA,
    fecha_inicio=datetime.fromisoformat("2026-10-06T17:00:00+00:00"),
    fecha_fin=datetime.fromisoformat("2026-10-06T20:00:00+00:00"),
    cronometro=CRONOMETRO,
    etiqueta="C1",
    minutos_tolerancia=20,
)
# La consulta a la tabla no trae la tolerancia (config_sistema no es legible).
EN_SERVIDOR = replace(RESERVA, minutos_tolerancia=None)
EN_USO = replace(EN_SERVIDOR, estado=EstadoReserva.EN_USO, cronometro=None)


class Reloj:
    def __init__(self, ahora: datetime) -> None:
        self.ahora = ahora

    def __call__(self) -> datetime:
        return self.ahora


def _vm(local=RESERVA, servidor=EN_SERVIDOR, ahora=CONFIRMADA):
    auth, reservas, almacen = MagicMock(), MagicMock(), MagicMock()
    auth.usuario_actual = Usuario("uid", "Ana", "Pérez", None, "ana@itsx.edu.mx",
                                  MedioTransporte.VEHICULO)
    almacen.leer.return_value = local
    reservas.obtener_reserva.return_value = servidor
    reservas.reserva_vigente.return_value = servidor
    reservas.reglas.return_value = ReglasReserva(None, None)  # sin reglas, salvo que se indique
    al_salir, al_ver_cajones = MagicMock(), MagicMock()
    reloj = Reloj(ahora)
    vm = MiReservaViewModel(auth, reservas, almacen, al_salir=al_salir,
                            al_ver_cajones=al_ver_cajones, reloj=reloj)
    return vm, reservas, almacen, reloj, al_salir, al_ver_cajones


def _iniciado(**kwargs):
    """ViewModel ya iniciado, sin el ciclo de un segundo."""
    vm, *resto = _vm(**kwargs)

    async def escenario():
        await vm.iniciar()
        vm.liberar()

    asyncio.run(escenario())
    return vm, *resto


# --- Reserva confirmada (mockup "¡Reserva confirmada!") ---

def test_muestra_la_reserva_guardada_y_la_confirma_con_el_servidor():
    vm, reservas, *_ = _iniciado()
    reservas.obtener_reserva.assert_called_once_with("r1")
    assert vm.pantalla == PantallaReserva.ACTIVA
    assert vm.fase == FaseReserva.CONFIRMADA
    assert vm.banner == ("¡Reserva confirmada!", "El cajón C1 está reservado para ti.")
    assert not vm.banner_es_advertencia
    assert vm.horario == "Hoy · 11:00 a 14:00"
    assert vm.codigo_qr == "a" * 32
    assert vm.texto_conexion == "Conectado"
    # La tolerancia de la copia local se conserva aunque el servidor no la mande.
    assert vm.cronometro == ("Tiempo para llegar", "Después tendrás 20 min de tolerancia",
                             "60:00", False)
    assert vm.puede_cancelar and not vm.en_uso


def test_cuenta_regresiva_avanza_con_el_reloj():
    vm, _, _, reloj, *_ = _iniciado()
    reloj.ahora = CONFIRMADA + timedelta(minutes=12, seconds=30)
    assert vm.cronometro[2] == "47:30"


@pytest.mark.parametrize(
    ("segundos", "texto"),
    [(0, "00:00"), (-5, "00:00"), (59, "00:59"), (3600, "60:00"), (3601, "1:00:01"),
     (2 * 3600 + 5 * 60, "2:05:00")],
)
def test_formato_de_la_cuenta_regresiva(segundos, texto):
    assert _cuenta_regresiva(timedelta(seconds=segundos)) == texto


# --- Retraso y expiración (RF-07, RF-08) ---

def test_al_terminar_la_hora_para_llegar_avisa_el_retraso():
    vm, *_ = _iniciado(ahora=CRONOMETRO + timedelta(minutes=5))
    assert vm.fase == FaseReserva.RETRASO
    titulo, detalle = vm.banner
    assert titulo == "Vas con retraso"
    assert "Tienes 20 minutos de tolerancia" in detalle
    assert vm.banner_es_advertencia
    assert vm.cronometro == ("Tolerancia restante", None, "15:00", True)
    assert vm.puede_cancelar


def test_sin_tolerancia_conocida_no_inventa_el_tiempo():
    local = replace(RESERVA, minutos_tolerancia=None)
    vm, *_ = _iniciado(local=local, ahora=CRONOMETRO + timedelta(minutes=5))
    assert vm.cronometro[2] == "--:--"
    assert "20" not in vm.banner[1]


def test_al_vencer_la_tolerancia_la_reserva_expira():
    # El barrido del servidor aún no la marca (cron apagado o atrasado).
    vm, reservas, almacen, *_ = _iniciado(ahora=CRONOMETRO + timedelta(minutes=20))
    assert vm.pantalla == PantallaReserva.EXPIRADA
    assert vm.resultado.titulo == "Tu reserva expiró"
    assert "20 minutos de tolerancia" in vm.resultado.detalle
    assert "cajón C1 quedó libre" in vm.resultado.detalle
    assert vm.resultado.boton == "Ver cajones disponibles"
    almacen.borrar.assert_called()
    assert vm.codigo_qr is None


def test_llegada_registrada_al_ultimo_momento_no_se_da_por_expirada():
    vm, *_ = _iniciado(servidor=EN_USO, ahora=CRONOMETRO + timedelta(minutes=20))
    assert vm.pantalla == PantallaReserva.ACTIVA
    assert vm.fase == FaseReserva.EN_USO


def test_expirada_en_el_servidor():
    vm, _, almacen, _, _, al_ver_cajones = _iniciado(
        servidor=replace(EN_SERVIDOR, estado=EstadoReserva.EXPIRADA))
    assert vm.pantalla == PantallaReserva.EXPIRADA
    almacen.borrar.assert_called()
    asyncio.run(vm.accion_resultado())
    al_ver_cajones.assert_called_once()


# --- Sin internet (RNF-08) ---

def test_sin_internet_sigue_mostrando_el_qr_guardado():
    vm, reservas, *_ = _vm()
    reservas.obtener_reserva.side_effect = ReservasNoDisponiblesError("x", sin_red=True)

    async def escenario():
        await vm.iniciar()
        vm.liberar()

    asyncio.run(escenario())
    assert vm.pantalla == PantallaReserva.ACTIVA
    assert vm.codigo_qr == "a" * 32
    assert vm.texto_conexion == "Sin conexión"


def test_sin_copia_local_ni_internet():
    vm, reservas, *_ = _vm(local=None)
    reservas.reserva_vigente.side_effect = ReservasNoDisponiblesError("x", sin_red=True)

    async def escenario():
        await vm.iniciar()
        vm.liberar()
        assert vm.pantalla == PantallaReserva.ERROR
        assert vm.resultado.titulo == "No se pudo conectar"
        assert vm.resultado.boton == "Reintentar"
        reservas.reserva_vigente.side_effect = None
        await vm.accion_resultado()
        assert vm.pantalla == PantallaReserva.ACTIVA

    asyncio.run(escenario())


def test_sin_copia_local_la_busca_en_el_servidor_y_la_guarda():
    vm, reservas, almacen, *_ = _iniciado(local=None)
    reservas.reserva_vigente.assert_called_once_with("uid")
    almacen.guardar.assert_called_once_with("uid", EN_SERVIDOR)
    assert vm.etiqueta == "C1"


def test_sin_reserva_vigente():
    vm, _, _, _, _, al_ver_cajones = _iniciado(local=None, servidor=None)
    assert vm.pantalla == PantallaReserva.SIN_RESERVA
    asyncio.run(vm.accion_resultado())
    al_ver_cajones.assert_called_once()


def test_la_cuenta_regresiva_no_se_congela_si_el_servidor_tarda():
    import time

    def lento(*_):
        time.sleep(1.5)  # red lenta del teléfono
        return EN_USO

    async def escenario():
        vm, reservas, *_ = _vm(local=EN_USO)
        vm._intervalo = 1
        reservas.obtener_reserva.side_effect = lento
        marcas: list[float] = []
        vm.add_listener(lambda: marcas.append(time.monotonic()))
        tarea = asyncio.get_running_loop().create_task(vm.iniciar())
        await asyncio.sleep(3.6)
        vm.liberar()
        tarea.cancel()
        pausas = [b - a for a, b in zip(marcas, marcas[1:], strict=False)]
        assert len(marcas) >= 4 and max(pausas) < 1.4

    asyncio.run(escenario())


def test_cerrar_la_pantalla_durante_la_consulta_no_deja_el_ciclo_corriendo():
    vm, *_ = _vm()

    async def escenario():
        vm.liberar()
        await vm.iniciar()
        assert vm._ciclo is None

    asyncio.run(escenario())


# --- Cancelar (mockups de la hoja y "Reserva cancelada") ---

def test_cancelar_pide_confirmacion_y_libera_el_cajon():
    vm, reservas, almacen, _, al_salir, _ = _iniciado()
    vm.pedir_cancelar()
    assert vm.confirmacion == Confirmacion.CANCELAR
    titulo, detalle, boton = vm.texto_confirmacion
    assert (titulo, boton) == ("¿Cancelar tu reserva?", "Sí, cancelar reserva")
    assert "cajón C1 quedará libre" in detalle

    asyncio.run(vm.confirmar_accion())

    reservas.cancelar_reserva.assert_called_once_with("r1")
    assert vm.pantalla == PantallaReserva.CANCELADA
    assert vm.confirmacion is None
    assert vm.resultado.titulo == "Reserva cancelada"
    assert vm.resultado.detalle == "Tu código QR ya no es válido y el cajón C1 quedó libre."
    almacen.borrar.assert_called()
    asyncio.run(vm.accion_resultado())
    al_salir.assert_called_once()


def test_mantener_reserva_cierra_la_confirmacion():
    vm, reservas, *_ = _iniciado()
    vm.pedir_cancelar()
    vm.descartar_confirmacion()
    assert vm.confirmacion is None
    reservas.cancelar_reserva.assert_not_called()


def test_cancelar_despues_de_llegar_sincroniza_el_estado():
    vm, reservas, *_ = _iniciado()
    reservas.cancelar_reserva.side_effect = ReservaError(
        "ESTADO_INVALIDO", "Solo puedes cancelar una reserva antes de tu llegada.", 409)
    reservas.obtener_reserva.return_value = EN_USO
    vm.pedir_cancelar()
    asyncio.run(vm.confirmar_accion())
    assert vm.alerta.titulo == "No se pudo cancelar la reserva"
    assert vm.fase == FaseReserva.EN_USO
    assert not vm.procesando


def test_cancelar_sin_internet():
    vm, reservas, *_ = _iniciado()
    reservas.cancelar_reserva.side_effect = ReservasNoDisponiblesError("x", sin_red=True)
    vm.pedir_cancelar()
    asyncio.run(vm.confirmar_accion())
    assert vm.pantalla == PantallaReserva.ACTIVA
    assert vm.alerta.titulo == "No se pudo conectar"


# --- En uso: extender (RF-12) y confirmar salida (RF-13) ---

def test_en_uso_como_el_mockup():
    llegada = CONFIRMADA + timedelta(minutes=50)
    vm, *_ = _iniciado(servidor=replace(EN_USO, fecha_llegada=llegada),
                       ahora=CONFIRMADA + timedelta(hours=2))
    assert vm.codigo_qr is None
    assert vm.en_uso and not vm.puede_cancelar
    assert vm.banner is None
    assert vm.detalle_cajon == "Llegada registrada · En uso"
    assert vm.cronometro == ("Tiempo restante de tu reserva", "Termina a las 14:00", "02:00:00",
                             False)
    assert vm.filas_uso == [("Llegada registrada", "10:50"), ("Hora de fin", "14:00"),
                            ("Duración total", "3 h")]


def test_extender_actualiza_la_hora_de_fin():
    vm, reservas, almacen, *_ = _iniciado(servidor=EN_USO)
    nuevo_fin = datetime.fromisoformat("2026-10-06T21:00:00+00:00")
    reservas.extender_reserva.return_value = nuevo_fin
    asyncio.run(vm.extender())
    reservas.extender_reserva.assert_called_once_with("r1")
    assert vm.reserva.fecha_fin == nuevo_fin
    assert vm.banner[1] == "Extendiste tu reserva hasta las 15:00."
    almacen.guardar.assert_called_with("uid", vm.reserva)


def test_extension_rechazada_muestra_el_motivo():
    vm, reservas, *_ = _iniciado(servidor=EN_USO)
    reservas.extender_reserva.side_effect = ReservaError(
        "EXTENSION_NO_PERMITIDA", "No puedes extender: se excedería el horario.", 422)
    asyncio.run(vm.extender())
    assert vm.alerta.titulo == "No se pudo extender la reserva"
    assert vm.alerta.detalle.startswith("No puedes extender")


def test_confirmar_salida():
    vm, reservas, *_ = _iniciado(servidor=EN_USO)
    vm.pedir_salida()
    assert vm.texto_confirmacion[0] == "¿Confirmar tu salida?"
    asyncio.run(vm.confirmar_accion())
    reservas.confirmar_salida.assert_called_once_with("r1")
    assert vm.pantalla == PantallaReserva.FINALIZADA
    assert vm.resultado.titulo == "Salida confirmada"
    assert vm.resultado.detalle == ("Gracias por usar el estacionamiento. El cajón C1 ya está "
                                    "libre para otros estudiantes.")


def test_horario_terminado_pide_confirmar_la_salida():
    vm, *_ = _iniciado(servidor=EN_USO, ahora=EN_USO.fecha_fin + timedelta(minutes=1))
    assert vm.cronometro == ("Tiempo restante de tu reserva", "Terminó a las 14:00", "00:00:00",
                             True)
    assert vm.aviso_fin == ("Tu horario terminó",
                            "Confirma tu salida o extiende tu estancia una hora más.")


# --- En uso: fin próximo (RF-12) dentro de la app, sin depender de la notificación ---

REGLAS = ReglasReserva(60, 20, minutos_aviso_fin=10, horas_maximas=15)


def _en_uso_con_reglas(ahora, reglas=REGLAS):
    vm, reservas, *resto = _vm(local=None, servidor=EN_USO, ahora=ahora)
    reservas.reglas.return_value = reglas
    asyncio.run(vm.actualizar())
    return vm, reservas, *resto


def test_antes_del_aviso_no_hay_recuadro_de_fin():
    vm, reservas, *_ = _en_uso_con_reglas(EN_USO.fecha_fin - timedelta(minutes=11))
    reservas.reglas.assert_called_once()
    assert not vm.fin_proximo and vm.aviso_fin is None
    assert vm.nota_uso.startswith("Te avisaremos antes")


def test_dentro_del_aviso_ofrece_salir_o_extender():
    vm, *_ = _en_uso_con_reglas(EN_USO.fecha_fin - timedelta(minutes=9, seconds=30))
    assert vm.aviso_fin == ("Tu reserva está por terminar",
                            "Quedan 10 minutos. Confirma tu salida o extiende tu estancia una "
                            "hora más.")
    assert vm.nota_uso == "Solo puedes extender si tu reserva no supera el límite de 15 horas."


def test_las_reglas_se_leen_una_sola_vez():
    vm, reservas, *_ = _en_uso_con_reglas(EN_USO.fecha_fin - timedelta(minutes=30))
    asyncio.run(vm.actualizar())
    reservas.reglas.assert_called_once()


def test_sin_reglas_usa_la_marca_del_barrido():
    vm, reservas, *_ = _vm(local=None, servidor=replace(EN_USO, aviso_fin_enviado=True),
                           ahora=EN_USO.fecha_fin - timedelta(minutes=5))
    reservas.reglas.side_effect = ReservasNoDisponiblesError("HTTP 404")
    asyncio.run(vm.actualizar())
    assert vm.aviso_fin[0] == "Tu reserva está por terminar"
    assert vm.nota_uso == "Solo puedes extender si tu reserva no supera la duración máxima permitida."


def test_al_extender_desaparece_el_recuadro_de_fin():
    vm, reservas, *_ = _en_uso_con_reglas(EN_USO.fecha_fin - timedelta(minutes=5))
    reservas.extender_reserva.return_value = EN_USO.fecha_fin + timedelta(hours=1)
    asyncio.run(vm.extender())
    assert vm.aviso_fin is None
    assert vm.banner == ("Reserva extendida", "Extendiste tu reserva hasta las 15:00.")


def test_vista_fin_proximo_como_el_mockup():
    vm, *_ = _en_uso_con_reglas(EN_USO.fecha_fin - timedelta(minutes=5))
    vista = MiReservaView(vm)
    assert vista._aviso_fin.visible
    assert vista._titulo_aviso.value == "Tu reserva está por terminar"
    assert vista._extender.content == "Extender 1 hora"
    assert vista._salida_aviso.visible and vista._salida.visible
    assert vista._nota_uso.controls[1].value.startswith("Solo puedes extender")


# --- Vista ---

def test_vista_reserva_confirmada_como_el_mockup():
    vm, *_ = _iniciado()
    vista = MiReservaView(vm)
    assert vista._banner.titulo == "¡Reserva confirmada!"
    assert vista._recuadro.titulo == "Cajón C1"
    assert isinstance(vista._qr.content, ft.Image)
    assert vista._qr.content.src.startswith(b"\x89PNG")
    assert vista._texto_conexion.value == "Conectado"
    assert vista._tiempo.value == "60:00"
    assert vista._cancelar.visible and not vista._salida.visible
    assert vista._barra.visible
    assert vista._resultado.titulo is None


def test_vista_en_uso_como_el_mockup():
    vm, *_ = _iniciado(servidor=EN_USO, ahora=CONFIRMADA + timedelta(hours=2))
    vista = MiReservaView(vm)
    assert vista._banner.titulo is None
    assert vista._recuadro.titulo == "Cajón C1"
    assert vista._recuadro._detalle.value == "Llegada registrada · En uso"
    assert not vista._tarjeta_qr.visible
    assert vista._titulo_tiempo.value == "Tiempo restante de tu reserva"
    assert vista._tiempo.value == "02:00:00"
    assert vista._nota_uso.visible and vista._tabla_uso.visible
    assert vista._salida.visible and not vista._cancelar.visible


def test_vista_retraso_en_naranja():
    vm, *_ = _iniciado(ahora=CRONOMETRO + timedelta(minutes=5))
    vista = MiReservaView(vm)
    assert vista._banner.titulo == "Vas con retraso"
    assert vista._titulo_tiempo.value == "Tolerancia restante"
    assert vista._tiempo.color == "#F2A83B"


def test_vista_resultado_sin_barra_de_titulo():
    vm, *_ = _iniciado()
    vm.pedir_cancelar()
    vista = MiReservaView(vm)
    assert vista._titulo_hoja.value == "¿Cancelar tu reserva?"
    assert vista._confirmar_peligro.visible and not vista._confirmar_normal.visible
    asyncio.run(vm.confirmar_accion())
    vista._render()
    assert vista._resultado.titulo == "Reserva cancelada"
    assert not vista._barra.visible
    assert not vista._activa.visible


def test_mi_reserva_consulta_cuando_mqtt_cambia_su_cajon():
    from parking_app.models.cajon_estacionamiento import EstadoSistema
    from parking_app.models.evento_ocupacion import EventoOcupacion, EventoSistema
    from parking_app.viewmodels.aviso_cambios import AvisoDeCambios
    from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel

    async def escenario():
        ocupacion = OcupacionViewModel(MagicMock(), MagicMock(), MagicMock(), MagicMock(), 60,
                                       MagicMock())
        for modulo in range(1, 5):
            ocupacion._recibir_evento(EventoOcupacion(id_modulo=modulo, estado="libre"))
        vm, reservas, *_ = _vm()
        vm._aviso = AvisoDeCambios(ocupacion, vm.actualizar, lambda: vm.etiqueta or None)
        await vm.iniciar()
        llamadas = reservas.obtener_reserva.call_count

        # Un cambio en otro cajón (C3) no le importa a esta reserva (C1).
        ocupacion._recibir_sistema(EventoSistema(id_modulo=3, estado=EstadoSistema.RESERVADO))
        await asyncio.sleep(0.05)
        assert reservas.obtener_reserva.call_count == llamadas

        ocupacion._recibir_sistema(EventoSistema(id_modulo=1, estado=EstadoSistema.RESERVADO))
        await asyncio.sleep(0.05)
        assert reservas.obtener_reserva.call_count == llamadas + 1
        vm.liberar()

    asyncio.run(escenario())
