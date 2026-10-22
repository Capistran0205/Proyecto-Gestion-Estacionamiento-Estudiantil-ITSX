import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from parking_app.core.config import ZONA_HORARIA
from parking_app.core.observable import Observable
from parking_app.models.reserva_cajon import EstadoReserva, ReglasReserva, ReservaCajon
from parking_app.services.almacen_reserva import AlmacenReserva
from parking_app.services.auth_service import AuthService
from parking_app.services.reservas_service import (
    ReservaError,
    ReservasNoDisponiblesError,
    ReservasService,
)
from parking_app.viewmodels.alerta import Alerta
from parking_app.viewmodels.aviso_cambios import AvisoDeCambios
from parking_app.viewmodels.formato import cuenta_regresiva, hh_mm_ss, hora_local, horas_totales
from parking_app.viewmodels.navegacion import Navegar, llamar
from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel
from parking_app.viewmodels.reservar_viewmodel import ALERTA_SESION, alerta_no_disponible

logger = logging.getLogger(__name__)

# Cada cuántos segundos se consulta el estado de la reserva mientras la pantalla
# está abierta (llegada registrada por el administrador, expiración del barrido...).
# Respaldo: además se consulta en cuanto MQTT reporta un cambio en el cajón (AvisoDeCambios).
INTERVALO_CONSULTA_S = 30


class PantallaReserva(StrEnum):
    CARGANDO = "cargando"
    ACTIVA = "activa"
    CANCELADA = "cancelada"
    EXPIRADA = "expirada"
    FINALIZADA = "finalizada"
    SIN_RESERVA = "sin_reserva"
    ERROR = "error"


TERMINALES = {PantallaReserva.CANCELADA, PantallaReserva.EXPIRADA, PantallaReserva.FINALIZADA}
PANTALLA_DE_ESTADO = {
    EstadoReserva.CANCELADA: PantallaReserva.CANCELADA,
    EstadoReserva.EXPIRADA: PantallaReserva.EXPIRADA,
    EstadoReserva.FINALIZADA: PantallaReserva.FINALIZADA,
}


class FaseReserva(StrEnum):
    CONFIRMADA = "confirmada"  # pendiente de llegada, dentro de la hora para llegar
    RETRASO = "retraso"  # pendiente de llegada, en la tolerancia (RF-07)
    EN_USO = "en_uso"  # el administrador registró la llegada


class Confirmacion(StrEnum):
    CANCELAR = "cancelar"
    SALIDA = "salida"


@dataclass(frozen=True)
class Resultado:
    titulo: str
    detalle: str
    boton: str


_hora = hora_local
_cuenta_regresiva = cuenta_regresiva


# Clase representativa de "Mi reserva" (paso 3 del Módulo B): QR, cuenta regresiva
# de llegada y tolerancia (RF-06–08), cancelar (RF-15), extender (RF-12) y
# confirmar salida (RF-13). Funciona sin internet con la copia local (RNF-08).
class MiReservaViewModel(Observable):
    def __init__(
        self,
        auth_service: AuthService,
        reservas_service: ReservasService,
        almacen: AlmacenReserva,
        al_salir: Navegar,
        al_ver_cajones: Navegar,
        reloj: Callable[[], datetime] | None = None,
        intervalo_consulta_s: int = INTERVALO_CONSULTA_S,
        ocupacion: OcupacionViewModel | None = None,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self._aviso = (AvisoDeCambios(ocupacion, self.actualizar, lambda: self.etiqueta or None)
                       if ocupacion is not None else None)
        self._reservas = reservas_service
        self._almacen = almacen
        self._al_salir = al_salir
        self._al_ver_cajones = al_ver_cajones
        self._reloj = reloj or (lambda: datetime.now(UTC))
        self._intervalo = intervalo_consulta_s

        self.pantalla = PantallaReserva.CARGANDO
        self.reserva: ReservaCajon | None = None
        self.conectado = True
        self.alerta: Alerta | None = None
        self.mensaje: str | None = None
        self.confirmacion: Confirmacion | None = None
        self.procesando = False
        # Aviso de fin y límite de horas (config_sistema vía reglas-reserva); se leen una vez.
        self.reglas: ReglasReserva | None = None
        self._consultando = False
        self._ciclo: asyncio.Task[None] | None = None
        self._consultas: set[asyncio.Task[None]] = set()
        self._liberado = False

    # --- Ciclo de vida ---

    async def iniciar(self) -> None:
        usuario = self._auth.usuario_actual
        local = self._almacen.leer(usuario.id_usuario) if usuario else None
        if local is not None and local.estado.vigente:
            # Se muestra de inmediato (también sin internet) y luego se confirma.
            self.reserva = local
            self.pantalla = PantallaReserva.ACTIVA
            self.notify_listeners()
        # El reloj arranca ya: la copia local cuenta aunque el servidor tarde en responder.
        # Si la pantalla se cierra durante la consulta, liberar() lo detiene.
        if not self._liberado:
            self._ciclo = asyncio.get_running_loop().create_task(self._correr())
        await self.actualizar()
        await self._revisar_tiempo()
        if not self._liberado and self._aviso is not None:
            self._aviso.escuchar()

    def liberar(self) -> None:
        self._liberado = True
        if self._aviso is not None:
            self._aviso.dejar()
        if self._ciclo is not None:
            self._ciclo.cancel()
            self._ciclo = None

    async def _correr(self) -> None:
        segundos = 0
        while self.pantalla not in TERMINALES:
            await asyncio.sleep(1)
            segundos += 1
            if segundos % self._intervalo == 0:
                # Aparte: si la red tarda, la cuenta regresiva no se congela.
                self._consultar_aparte()
            try:
                await self._revisar_tiempo()
            except Exception:
                logger.exception("Fallo al revisar el tiempo de la reserva")
            self.notify_listeners()

    def _consultar_aparte(self) -> None:
        async def consultar() -> None:
            try:
                await self.actualizar()
            except Exception:
                logger.exception("Fallo al actualizar la reserva")

        tarea = asyncio.get_running_loop().create_task(consultar())
        self._consultas.add(tarea)
        tarea.add_done_callback(self._consultas.discard)

    # --- Propiedades de presentación ---

    @property
    def activa(self) -> bool:
        return self.pantalla == PantallaReserva.ACTIVA and self.reserva is not None

    @property
    def fase(self) -> FaseReserva | None:
        r = self.reserva
        if not self.activa or r is None:
            return None
        if r.estado == EstadoReserva.EN_USO:
            return FaseReserva.EN_USO
        if r.cronometro is not None and self._reloj() >= r.cronometro:
            return FaseReserva.RETRASO
        return FaseReserva.CONFIRMADA

    @property
    def etiqueta(self) -> str:
        return self.reserva.etiqueta_cajon if self.reserva else ""

    @property
    def _tolerancia(self) -> int | None:
        return self.reserva.minutos_tolerancia if self.reserva else None

    @property
    def banner(self) -> tuple[str, str] | None:
        """(título, detalle) del recuadro de estado."""
        fase = self.fase
        if fase == FaseReserva.CONFIRMADA:
            return "¡Reserva confirmada!", f"El cajón {self.etiqueta} está reservado para ti."
        if fase == FaseReserva.RETRASO:
            if self._tolerancia is None:
                detalle = ("Se terminó tu hora para llegar. Si no llegas dentro de la tolerancia, "
                           "la reserva se cancelará.")
            else:
                detalle = (f"Se terminó tu hora para llegar. Tienes {self._tolerancia} minutos de "
                           "tolerancia; si no llegas, la reserva se cancelará.")
            return "Vas con retraso", detalle
        if fase == FaseReserva.EN_USO and self.mensaje:
            # El mockup "en uso" no lleva recuadro; solo aparece tras extender.
            return "Reserva extendida", self.mensaje
        return None

    @property
    def banner_es_advertencia(self) -> bool:
        return self.fase == FaseReserva.RETRASO

    @property
    def horario(self) -> str:
        r = self.reserva
        if r is None:
            return ""
        dia = r.fecha_inicio.astimezone(ZONA_HORARIA).date()
        hoy = self._reloj().astimezone(ZONA_HORARIA).date()
        if dia == hoy:
            texto_dia = "Hoy"
        elif dia == hoy + timedelta(days=1):
            texto_dia = "Mañana"
        else:
            texto_dia = dia.strftime("%d/%m/%Y")
        return f"{texto_dia} · {_hora(r.fecha_inicio)} a {_hora(r.fecha_fin)}"

    @property
    def detalle_cajon(self) -> str:
        """Segunda línea del recuadro del cajón: el horario, o "en uso" tras la llegada."""
        return "Llegada registrada · En uso" if self.fase == FaseReserva.EN_USO else self.horario

    @property
    def filas_uso(self) -> list[tuple[str, str]]:
        """Tabla del mockup "en uso": llegada, hora de fin y duración total."""
        r = self.reserva
        if r is None or self.fase != FaseReserva.EN_USO:
            return []
        llegada = _hora(r.fecha_llegada) if r.fecha_llegada else "--:--"
        return [
            ("Llegada registrada", llegada),
            ("Hora de fin", _hora(r.fecha_fin)),
            ("Duración total", horas_totales(r.fecha_inicio, r.fecha_fin)),
        ]

    @property
    def codigo_qr(self) -> str | None:
        """Solo antes de la llegada: el código es de un solo uso."""
        r = self.reserva
        if self.activa and r is not None and r.estado == EstadoReserva.PENDIENTE_LLEGADA:
            return r.codigo_qr
        return None

    @property
    def texto_conexion(self) -> str:
        return "Conectado" if self.conectado else "Sin conexión"

    @property
    def cronometro(self) -> tuple[str, str | None, str, bool] | None:
        """(título, detalle, tiempo, en alerta) de la cuenta regresiva."""
        r, fase, ahora = self.reserva, self.fase, self._reloj()
        if r is None or fase is None:
            return None
        if fase == FaseReserva.CONFIRMADA and r.cronometro is not None:
            detalle = (None if self._tolerancia is None
                       else f"Después tendrás {self._tolerancia} min de tolerancia")
            return "Tiempo para llegar", detalle, _cuenta_regresiva(r.cronometro - ahora), False
        if fase == FaseReserva.RETRASO:
            limite = r.limite_tolerancia
            tiempo = "--:--" if limite is None else _cuenta_regresiva(limite - ahora)
            return "Tolerancia restante", None, tiempo, True
        if fase == FaseReserva.EN_USO:
            if ahora >= r.fecha_fin:
                return ("Tiempo restante de tu reserva", f"Terminó a las {_hora(r.fecha_fin)}",
                        "00:00:00", True)
            return ("Tiempo restante de tu reserva", f"Termina a las {_hora(r.fecha_fin)}",
                    hh_mm_ss(r.fecha_fin - ahora), False)
        return None

    @property
    def fin_proximo(self) -> bool:
        """En uso y dentro del aviso de fin (RF-12) o ya pasada la hora de fin."""
        r = self.reserva
        if r is None or self.fase != FaseReserva.EN_USO:
            return False
        aviso = self.reglas.minutos_aviso_fin if self.reglas else None
        if aviso is None:
            return r.aviso_fin_enviado or self._reloj() >= r.fecha_fin
        return self._reloj() >= r.fecha_fin - timedelta(minutes=aviso)

    @property
    def aviso_fin(self) -> tuple[str, str] | None:
        """(título, detalle) del recuadro naranja con "Confirmar salida" y "Extender 1 hora"."""
        if not self.fin_proximo or self.reserva is None:
            return None
        accion = "Confirma tu salida o extiende tu estancia una hora más."
        restante = self.reserva.fecha_fin - self._reloj()
        if restante.total_seconds() <= 0:
            return "Tu horario terminó", accion
        minutos = math.ceil(restante.total_seconds() / 60)
        texto = "Queda 1 minuto" if minutos == 1 else f"Quedan {minutos} minutos"
        return "Tu reserva está por terminar", f"{texto}. {accion}"

    @property
    def nota_uso(self) -> str:
        if not self.fin_proximo:
            return ("Te avisaremos antes de que termine tu reserva para que confirmes tu salida "
                    "o la extiendas una hora más.")
        horas = self.reglas.horas_maximas if self.reglas else None
        limite = f"el límite de {horas} horas" if horas else "la duración máxima permitida"
        return f"Solo puedes extender si tu reserva no supera {limite}."

    @property
    def puede_cancelar(self) -> bool:
        return self.fase in (FaseReserva.CONFIRMADA, FaseReserva.RETRASO)

    @property
    def en_uso(self) -> bool:
        return self.fase == FaseReserva.EN_USO

    @property
    def texto_confirmacion(self) -> tuple[str, str, str] | None:
        """(título, detalle, botón) de la hoja de confirmación."""
        if self.confirmacion == Confirmacion.CANCELAR:
            return (
                "¿Cancelar tu reserva?",
                f"El código QR dejará de ser válido y el cajón {self.etiqueta} quedará libre para "
                "otros estudiantes. Esta acción no se puede deshacer.",
                "Sí, cancelar reserva",
            )
        if self.confirmacion == Confirmacion.SALIDA:
            return (
                "¿Confirmar tu salida?",
                f"Tu reserva terminará y el cajón {self.etiqueta} quedará libre para otros "
                "estudiantes. Esta acción no se puede deshacer.",
                "Sí, confirmar salida",
            )
        return None

    @property
    def resultado(self) -> Resultado | None:
        e = self.etiqueta
        if self.pantalla == PantallaReserva.CANCELADA:
            return Resultado("Reserva cancelada",
                             f"Tu código QR ya no es válido y el cajón {e} quedó libre.",
                             "Volver al inicio")
        if self.pantalla == PantallaReserva.EXPIRADA:
            tolerancia = ("del tiempo de tolerancia" if self._tolerancia is None
                          else f"de los {self._tolerancia} minutos de tolerancia")
            return Resultado("Tu reserva expiró",
                             f"No llegaste dentro {tolerancia}. La reserva se canceló, tu código "
                             f"QR ya no es válido y el cajón {e} quedó libre.",
                             "Ver cajones disponibles")
        if self.pantalla == PantallaReserva.FINALIZADA:
            return Resultado("Salida confirmada",
                             f"Gracias por usar el estacionamiento. El cajón {e} ya está libre "
                             "para otros estudiantes.",
                             "Volver al inicio")
        if self.pantalla == PantallaReserva.SIN_RESERVA:
            return Resultado("No tienes una reserva activa",
                             "Elige un cajón libre en el mapa para reservar.",
                             "Ver cajones disponibles")
        if self.pantalla == PantallaReserva.ERROR and self.alerta is not None:
            return Resultado(self.alerta.titulo, self.alerta.detalle or "", "Reintentar")
        return None

    # --- Comandos ---

    async def actualizar(self) -> None:
        """Consulta el estado de la reserva en el servidor."""
        usuario = self._auth.usuario_actual
        if self._consultando or usuario is None or self.pantalla in TERMINALES:
            return
        self._consultando = True
        try:
            if self.reserva is not None:
                servidor = await asyncio.to_thread(
                    self._reservas.obtener_reserva, self.reserva.id_reserva)
            else:
                servidor = await asyncio.to_thread(
                    self._reservas.reserva_vigente, usuario.id_usuario)
        except ReservaError as e:
            logger.warning("Consulta de la reserva rechazada: %s", e.codigo)
            if self.reserva is None:
                self.alerta = ALERTA_SESION if e.codigo == "NO_AUTENTICADO" else Alerta(
                    "No se pudo cargar tu reserva", e.mensaje)
                self.pantalla = PantallaReserva.ERROR
        except ReservasNoDisponiblesError as e:
            # Sin servidor: se sigue mostrando la copia local (RNF-08).
            self.conectado = False
            if self.reserva is None:
                self.alerta = alerta_no_disponible(e)
                self.pantalla = PantallaReserva.ERROR
        else:
            self.conectado = True
            self._aplicar(servidor, usuario.id_usuario)
            if self.reglas is None and self.en_uso:
                await self._leer_reglas()
        finally:
            self._consultando = False
        self.notify_listeners()

    async def _leer_reglas(self) -> None:
        try:
            self.reglas = await asyncio.to_thread(self._reservas.reglas)
        except (ReservaError, ReservasNoDisponiblesError):
            # Sin reglas el aviso de fin sale cuando el barrido lo marque (aviso_fin_enviado).
            logger.warning("No se pudieron leer las reglas de reserva", exc_info=True)

    def pedir_cancelar(self) -> None:
        if self.puede_cancelar and not self.procesando:
            self.confirmacion = Confirmacion.CANCELAR
            self.notify_listeners()

    def pedir_salida(self) -> None:
        if self.en_uso and not self.procesando:
            self.confirmacion = Confirmacion.SALIDA
            self.notify_listeners()

    def descartar_confirmacion(self) -> None:
        if self.confirmacion is not None:
            self.confirmacion = None
            self.notify_listeners()

    async def confirmar_accion(self) -> None:
        accion, self.confirmacion = self.confirmacion, None
        if accion == Confirmacion.CANCELAR:
            await self._ejecutar(self._reservas.cancelar_reserva, PantallaReserva.CANCELADA,
                                 "No se pudo cancelar la reserva")
        elif accion == Confirmacion.SALIDA:
            await self._ejecutar(self._reservas.confirmar_salida, PantallaReserva.FINALIZADA,
                                 "No se pudo confirmar la salida")

    async def extender(self) -> None:
        """+1 h (RF-12): el backend valida el horario y la duración máxima."""
        r = self.reserva
        if r is None or not self.en_uso or self.procesando:
            return
        self._empezar_accion()
        try:
            nuevo_fin = await asyncio.to_thread(self._reservas.extender_reserva, r.id_reserva)
        except ReservaError as e:
            await self._error_de_accion(e, "No se pudo extender la reserva")
        except ReservasNoDisponiblesError as e:
            self.alerta = alerta_no_disponible(e)
        else:
            self.reserva = replace(r, fecha_fin=nuevo_fin)
            self._guardar()
            self.mensaje = f"Extendiste tu reserva hasta las {_hora(nuevo_fin)}."
        finally:
            self.procesando = False
        self.notify_listeners()

    async def regresar(self) -> None:
        await llamar(self._al_salir)

    async def accion_resultado(self) -> None:
        if self.pantalla in (PantallaReserva.CANCELADA, PantallaReserva.FINALIZADA):
            await llamar(self._al_salir)
        elif self.pantalla in (PantallaReserva.EXPIRADA, PantallaReserva.SIN_RESERVA):
            await llamar(self._al_ver_cajones)
        elif self.pantalla == PantallaReserva.ERROR:
            self.alerta = None
            self.pantalla = PantallaReserva.CARGANDO
            self.notify_listeners()
            await self.actualizar()

    # --- Internos ---

    def _aplicar(self, servidor: ReservaCajon | None, id_usuario: str) -> None:
        anterior = self.reserva
        if servidor is None:
            if anterior is not None:
                self._almacen.borrar()
            self.reserva = None
            self.pantalla = PantallaReserva.SIN_RESERVA
            return
        # La consulta no trae la tolerancia; se conserva la de la copia local.
        if anterior is not None:
            servidor = replace(
                servidor,
                etiqueta=servidor.etiqueta or anterior.etiqueta,
                minutos_tolerancia=servidor.minutos_tolerancia or anterior.minutos_tolerancia,
            )
        self.reserva = servidor
        if servidor.estado.vigente:
            self.pantalla = PantallaReserva.ACTIVA
            if servidor != anterior:
                self._almacen.guardar(id_usuario, servidor)
        else:
            self._terminar(PANTALLA_DE_ESTADO[servidor.estado])

    async def _revisar_tiempo(self) -> None:
        """Al vencer la tolerancia la reserva expira (RF-08). Antes de mostrarlo se
        consulta al servidor por si la llegada se registró en el último momento."""
        r = self.reserva
        if not self.activa or r is None or r.estado != EstadoReserva.PENDIENTE_LLEGADA:
            return
        limite = r.limite_tolerancia
        if limite is None or self._reloj() < limite:
            return
        await self.actualizar()
        r = self.reserva
        if self.activa and r is not None and r.estado == EstadoReserva.PENDIENTE_LLEGADA:
            self._terminar(PantallaReserva.EXPIRADA)

    async def _ejecutar(
        self, operacion: Callable[[str], object], final: PantallaReserva, titulo_error: str
    ) -> None:
        r = self.reserva
        if r is None or self.procesando:
            return
        self._empezar_accion()
        try:
            await asyncio.to_thread(operacion, r.id_reserva)
        except ReservaError as e:
            await self._error_de_accion(e, titulo_error)
        except ReservasNoDisponiblesError as e:
            self.alerta = alerta_no_disponible(e)
        else:
            self._terminar(final)
        finally:
            self.procesando = False
        self.notify_listeners()

    def _empezar_accion(self) -> None:
        self.procesando = True
        self.alerta = None
        self.mensaje = None
        self.notify_listeners()

    async def _error_de_accion(self, e: ReservaError, titulo: str) -> None:
        if e.codigo == "NO_AUTENTICADO":
            self.alerta = ALERTA_SESION
            return
        self.alerta = Alerta(titulo, e.mensaje)
        if e.codigo in ("ESTADO_INVALIDO", "RESERVA_NO_ENCONTRADA"):
            # La reserva cambió en el servidor (llegada, expiración...): se sincroniza.
            self.procesando = False
            await self.actualizar()

    def _terminar(self, pantalla: PantallaReserva) -> None:
        self.pantalla = pantalla
        self.confirmacion = None
        self.alerta = None
        self._almacen.borrar()

    def _guardar(self) -> None:
        usuario = self._auth.usuario_actual
        if usuario is not None and self.reserva is not None:
            self._almacen.guardar(usuario.id_usuario, self.reserva)
