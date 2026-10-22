import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from parking_app.core.observable import Observable
from parking_app.models.reserva_cajon import EstadoReserva, ReglasReserva, ReservaCajon
from parking_app.services.reservas_service import (
    ReservaError,
    ReservasNoDisponiblesError,
    ReservasService,
)
from parking_app.viewmodels.alerta import Alerta
from parking_app.viewmodels.aviso_cambios import AvisoDeCambios
from parking_app.viewmodels.formato import cuenta_regresiva, hora_local
from parking_app.viewmodels.navegacion import Navegar, llamar
from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel
from parking_app.viewmodels.reservar_viewmodel import alerta_no_disponible

logger = logging.getLogger(__name__)

# Respaldo: además se consulta en cuanto MQTT reporta un cambio en algún cajón.
INTERVALO_CONSULTA_S = 30
ALERTA_SESION = Alerta("Tu sesión expiró", "Cierra sesión y vuelve a entrar.")


class FaseAdmin(StrEnum):
    POR_LLEGAR = "por_llegar"  # dentro de la hora para llegar
    EN_TOLERANCIA = "en_tolerancia"  # se acabó la hora; corre la tolerancia (RF-07)
    EN_USO = "en_uso"  # llegada registrada (RF-10)


TITULOS = {
    FaseAdmin.POR_LLEGAR: "Por llegar",
    FaseAdmin.EN_TOLERANCIA: "En tolerancia",
    FaseAdmin.EN_USO: "En uso",
}


@dataclass(frozen=True)
class FilaReserva:
    id_reserva: str
    etiqueta: str
    fase: FaseAdmin
    titulo: str
    detalle: str
    tiempo: str


def _horario(r: ReservaCajon) -> str:
    return f"Reserva {hora_local(r.fecha_inicio)} a {hora_local(r.fecha_fin)}"


# Clase representativa de "Reservas" (administrador, Módulo C): reservas vigentes
# con sus tiempos en vivo y acceso al escáner. Lee las reservas directo (RLS de
# administrador) y la tolerancia de config_sistema vía reglas-reserva.
class AdminReservasViewModel(Observable):
    def __init__(
        self,
        reservas_service: ReservasService,
        al_regresar: Navegar,
        al_escanear: Navegar,
        reloj: Callable[[], datetime] | None = None,
        intervalo_consulta_s: int = INTERVALO_CONSULTA_S,
        ocupacion: OcupacionViewModel | None = None,
    ) -> None:
        super().__init__()
        self._reservas = reservas_service
        self._aviso = (AvisoDeCambios(ocupacion, self.actualizar)
                       if ocupacion is not None else None)
        self._al_regresar = al_regresar
        self._al_escanear = al_escanear
        self._reloj = reloj or (lambda: datetime.now(UTC))
        self._intervalo = intervalo_consulta_s

        self.reservas: list[ReservaCajon] = []
        self.reglas: ReglasReserva | None = None
        self.cargando = True
        self.alerta: Alerta | None = None
        self._consultando = False
        self._ciclo: asyncio.Task[None] | None = None
        self._consultas: set[asyncio.Task[None]] = set()
        self._liberado = False

    # --- Ciclo de vida ---

    async def iniciar(self) -> None:
        await self.actualizar()
        if not self._liberado:
            self._ciclo = asyncio.get_running_loop().create_task(self._correr())
            if self._aviso is not None:
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
        while True:
            await asyncio.sleep(1)
            segundos += 1
            if segundos % self._intervalo == 0:
                # Aparte: si la red tarda, los tiempos en vivo no se congelan.
                self._consultar_aparte()
            self.notify_listeners()

    def _consultar_aparte(self) -> None:
        async def consultar() -> None:
            try:
                await self.actualizar()
            except Exception:
                logger.exception("Fallo al actualizar las reservas")

        tarea = asyncio.get_running_loop().create_task(consultar())
        self._consultas.add(tarea)
        tarea.add_done_callback(self._consultas.discard)

    # --- Propiedades de presentación ---

    def _limite_tolerancia(self, r: ReservaCajon) -> datetime | None:
        if r.cronometro is None or self.reglas is None or self.reglas.minutos_tolerancia is None:
            return None
        return r.cronometro + timedelta(minutes=self.reglas.minutos_tolerancia)

    def _fase(self, r: ReservaCajon) -> FaseAdmin:
        if r.estado == EstadoReserva.EN_USO:
            return FaseAdmin.EN_USO
        if r.cronometro is not None and self._reloj() >= r.cronometro:
            return FaseAdmin.EN_TOLERANCIA
        return FaseAdmin.POR_LLEGAR

    @property
    def filas(self) -> list[FilaReserva]:
        ahora = self._reloj()
        filas = []
        for r in self.reservas:
            fase = self._fase(r)
            if fase == FaseAdmin.POR_LLEGAR:
                detalle = _horario(r)
                tiempo = cuenta_regresiva(r.cronometro - ahora) if r.cronometro else "--:--"
            elif fase == FaseAdmin.EN_TOLERANCIA:
                detalle = f"Retraso · {_horario(r)}"
                limite = self._limite_tolerancia(r)
                tiempo = cuenta_regresiva(limite - ahora) if limite else "--:--"
            else:
                llegada = hora_local(r.fecha_llegada) if r.fecha_llegada else "--:--"
                detalle = f"Llegó a las {llegada} · Sale {hora_local(r.fecha_fin)}"
                # Tiempo de uso que le queda (hh:mm); 00:00 si ya pasó su hora de salida.
                minutos = max(0, int((r.fecha_fin - ahora).total_seconds() // 60))
                tiempo = f"{minutos // 60:02}:{minutos % 60:02}"
            filas.append(FilaReserva(r.id_reserva, r.etiqueta_cajon, fase, TITULOS[fase],
                                     detalle, tiempo))
        return filas

    def contar(self, fase: FaseAdmin) -> int:
        return sum(1 for r in self.reservas if self._fase(r) == fase)

    @property
    def vacia(self) -> bool:
        return not self.cargando and not self.reservas

    # --- Comandos ---

    async def actualizar(self) -> None:
        if self._consultando:
            return
        self._consultando = True
        try:
            if self.reglas is None:
                try:
                    self.reglas = await asyncio.to_thread(self._reservas.reglas)
                except (ReservaError, ReservasNoDisponiblesError):
                    # Sin reglas solo falta la cuenta de la tolerancia ("--:--").
                    logger.warning("No se pudieron leer las reglas de reserva", exc_info=True)
            self.reservas = await asyncio.to_thread(self._reservas.reservas_activas)
            self.alerta = None
        except ReservaError as e:
            self.alerta = ALERTA_SESION if e.codigo == "NO_AUTENTICADO" else Alerta(
                "No se pudieron cargar las reservas", e.mensaje)
        except ReservasNoDisponiblesError as e:
            logger.warning("No se pudieron cargar las reservas: %s", e)
            self.alerta = alerta_no_disponible(e)
        finally:
            self._consultando = False
            self.cargando = False
        self.notify_listeners()

    async def escanear(self) -> None:
        await llamar(self._al_escanear)

    async def regresar(self) -> None:
        await llamar(self._al_regresar)
