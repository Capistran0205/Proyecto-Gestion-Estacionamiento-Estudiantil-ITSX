import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import IntEnum

from parking_app.core.config import ZONA_HORARIA
from parking_app.core.observable import Observable
from parking_app.models.cajon_estacionamiento import EstadoCajon
from parking_app.models.reserva_cajon import BloqueoCajon, ReservaCajon
from parking_app.models.usuario import MedioTransporte
from parking_app.services.almacen_reserva import AlmacenReserva
from parking_app.services.auth_service import AuthService
from parking_app.services.reservas_service import (
    ReservaError,
    ReservasNoDisponiblesError,
    ReservasService,
)
from parking_app.viewmodels.alerta import Alerta
from parking_app.viewmodels.navegacion import Navegar, llamar
from parking_app.viewmodels.ocupacion_viewmodel import TEXTOS_ESTADO, OcupacionViewModel

logger = logging.getLogger(__name__)

TOTAL_PASOS = 3

# Liberaciones en curso: la referencia evita que el recolector cancele la tarea
# cuando el ViewModel ya se descartó (al salir de la pantalla).
_TAREAS: set[asyncio.Task[None]] = set()

ALERTA_SIN_CONEXION = Alerta("No se pudo conectar", "Revisa tu conexión a internet e intenta de nuevo.")
ALERTA_SERVICIO = Alerta(
    "El servicio de reservas no está disponible",
    "No es un problema de tu conexión. Intenta de nuevo en unos minutos.",
)
ALERTA_SESION = Alerta("Tu sesión expiró", "Cierra sesión y vuelve a entrar para reservar.")


def alerta_no_disponible(e: ReservasNoDisponiblesError) -> Alerta:
    """Sin red vs. servidor con error (p. ej. función no desplegada)."""
    return ALERTA_SIN_CONEXION if e.sin_red else ALERTA_SERVICIO



# Rechazos de crear_reserva por la ventana de horario (RF-04): se vuelve al paso 2.
ERRORES_HORARIO = {
    "FUERA_DE_HORARIO": "Fuera del horario de operación",
    "DURACION_EXCEDIDA": "Excede la duración máxima",
    "OTRO_DIA": "Debe terminar el mismo día",
    "FIN_INVALIDO": "Debe ser posterior a la hora de inicio",
}
# Rechazos que invalidan el cajón apartado: se vuelve al paso 1.
ERRORES_BLOQUEO = {
    "BLOQUEO_EXPIRADO": "Se agotó el tiempo para reservar",
    "CAJON_NO_DISPONIBLE": "El cajón ya no está disponible",
    "INICIO_CAMBIO": "La hora de inicio cambió",
}
TEXTOS_TRANSPORTE = {MedioTransporte.VEHICULO: "Automóvil", MedioTransporte.MOTOCICLETA: "Motocicleta"}


class PasoReserva(IntEnum):
    ELEGIR = 1
    HORARIO = 2
    CONFIRMAR = 3


@dataclass(frozen=True)
class CajonReserva:
    etiqueta: str
    estado: EstadoCajon
    texto_estado: str
    seleccionado: bool
    tocable: bool


def _hora(fecha: datetime) -> str:
    return fecha.astimezone(ZONA_HORARIA).strftime("%H:%M")


def _duracion(inicio: datetime, fin: datetime) -> str:
    minutos = int((fin - inicio).total_seconds() // 60)
    horas, resto = divmod(minutos, 60)
    return f"{horas} h" if resto == 0 else f"{horas} h {resto} min"


def _minutos(total: int) -> str:
    horas, minutos = divmod(total, 60)
    partes = []
    if horas:
        partes.append("1 hora" if horas == 1 else f"{horas} horas")
    if minutos:
        partes.append("1 minuto" if minutos == 1 else f"{minutos} minutos")
    return " ".join(partes) or "0 minutos"


# Clase representativa del flujo "Reservar cajón" en 3 pasos (RNF-04):
# 1. elegir un cajón libre (se aparta con bloquear-cajon), 2. elegir la hora de
# fin, 3. confirmar (crear-reserva). Salir sin terminar libera el cajón (RF-03).
class ReservarViewModel(Observable):
    def __init__(
        self,
        auth_service: AuthService,
        ocupacion: OcupacionViewModel,
        reservas_service: ReservasService,
        almacen: AlmacenReserva,
        al_salir: Navegar,
        al_reserva_creada: Navegar,
        al_ver_reserva: Navegar | None = None,
        etiqueta_inicial: str | None = None,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self.ocupacion = ocupacion
        self._reservas = reservas_service
        self._almacen = almacen
        self._al_salir = al_salir
        self._al_reserva_creada = al_reserva_creada
        self._al_ver_reserva = al_ver_reserva
        self._etiqueta_inicial = etiqueta_inicial

        self.paso = PasoReserva.ELEGIR
        self.bloqueo: BloqueoCajon | None = None
        self.fin: datetime | None = None
        self.alerta: Alerta | None = None
        self.error_fin: str | None = None
        self.cargando = False
        self.tiene_reserva_activa = False
        self.reserva: ReservaCajon | None = None
        self._escuchando = False

    # --- Ciclo de vida ---

    async def iniciar(self) -> None:
        # El mapa del paso 1 refleja el estado en vivo del ViewModel de ocupación.
        self.ocupacion.add_listener(self.notify_listeners)
        self._escuchando = True
        if self._reserva_guardada() is not None:
            # RF-09 sin ir a la red: así el QR se puede abrir también sin internet.
            self.tiene_reserva_activa = True
            self.notify_listeners()
            return
        if self._etiqueta_inicial:
            await self.seleccionar(self._etiqueta_inicial)

    def liberar(self) -> None:
        """Al salir de la pantalla: deja de escuchar y suelta el cajón si no se reservó."""
        if self._escuchando:
            self.ocupacion.remove_listener(self.notify_listeners)
            self._escuchando = False
        self._soltar_bloqueo()

    # --- Propiedades de presentación ---

    @property
    def numero_paso(self) -> int:
        return int(self.paso)

    @property
    def total_pasos(self) -> int:
        return TOTAL_PASOS

    @property
    def etiqueta(self) -> str | None:
        return self.bloqueo.etiqueta if self.bloqueo else None

    @property
    def cajones(self) -> list[CajonReserva]:
        resultado = []
        for c in self.ocupacion.cajones:
            propio = c.etiqueta == self.etiqueta
            # El cajón apartado por este estudiante se ve "bloqueado" y seleccionado
            # aunque el mensaje MQTT todavía no haya llegado.
            estado = EstadoCajon.BLOQUEADO if propio else c.estado
            resultado.append(CajonReserva(
                etiqueta=c.etiqueta,
                estado=estado,
                texto_estado=TEXTOS_ESTADO[estado],
                seleccionado=propio,
                tocable=c.seleccionable and not self.cargando,
            ))
        return resultado

    @property
    def subtitulo_cajon(self) -> str:
        if self.paso == PasoReserva.ELEGIR:
            return "Seleccionado para reservar"
        return "Apartado para ti mientras completas la reserva"

    @property
    def hora_inicio(self) -> str:
        return _hora(self.bloqueo.fecha_inicio) if self.bloqueo else ""

    @property
    def opciones_fin(self) -> list[tuple[str, str]]:
        """(clave, "hh:mm") de cada hora de fin válida, en horas completas."""
        if self.bloqueo is None:
            return []
        opciones = []
        fin = self.bloqueo.fin_minimo
        while fin <= self.bloqueo.fin_maximo:
            opciones.append((fin.isoformat(), _hora(fin)))
            fin += timedelta(hours=1)
        return opciones

    @property
    def clave_fin(self) -> str | None:
        return self.fin.isoformat() if self.fin else None

    @property
    def duracion(self) -> str:
        if self.bloqueo is None or self.fin is None:
            return ""
        return _duracion(self.bloqueo.fecha_inicio, self.fin)

    @property
    def resumen(self) -> list[tuple[str, str]]:
        if self.bloqueo is None or self.fin is None:
            return []
        usuario = self._auth.usuario_actual
        medio = usuario.medio_transporte if usuario else None
        return [
            ("Cajón", self.bloqueo.etiqueta),
            ("Fecha", self.bloqueo.fecha_inicio.astimezone(ZONA_HORARIA).strftime("%d/%m/%Y")),
            ("Hora de inicio", self.hora_inicio),
            ("Hora de fin", _hora(self.fin)),
            ("Duración", self.duracion),
            ("Medio de transporte", TEXTOS_TRANSPORTE.get(medio, "Sin registrar")),
        ]

    @property
    def avisos(self) -> list[list[tuple[str, bool]]]:
        """Recuadro "Antes de confirmar": fragmentos (texto, en negritas)."""
        llegada = self.bloqueo.minutos_llegada if self.bloqueo else None
        tolerancia = self.bloqueo.minutos_tolerancia if self.bloqueo else None
        if llegada is not None and tolerancia is not None:
            tiempo = [
                ("Tendrás ", False), (_minutos(llegada), True),
                (" para llegar al estacionamiento, más ", False), (_minutos(tolerancia), True),
                (" de tolerancia.", False),
            ]
        else:
            tiempo = [("Tendrás un tiempo límite para llegar al estacionamiento, más un periodo "
                       "de tolerancia.", False)]
        return [
            tiempo,
            [("Si no llegas a tiempo, la reserva se cancelará y el cajón quedará libre.", False)],
            [("Recibirás un código QR para mostrarlo en la caseta al llegar.", False)],
        ]

    @property
    def puede_ver_reserva(self) -> bool:
        return self._al_ver_reserva is not None

    # --- Comandos ---

    async def seleccionar(self, etiqueta: str) -> None:
        """Paso 1: tocar un cajón libre lo aparta (bloquear-cajon, RF-02)."""
        if self.cargando or etiqueta == self.etiqueta:
            return
        cajon = self.ocupacion.cajon(etiqueta)
        if cajon is None or not cajon.seleccionable:
            return
        self.alerta = None
        self.cargando = True
        self.notify_listeners()
        try:
            bloqueo = await asyncio.to_thread(self._reservas.bloquear_cajon, cajon.id_cajon)
        except ReservaError as e:
            self._error_al_bloquear(e)
        except ReservasNoDisponiblesError as e:
            logger.exception("Fallo al apartar el cajón %s", etiqueta)
            self.alerta = alerta_no_disponible(e)
        else:
            # Si había otro cajón apartado, el backend ya lo liberó.
            self.bloqueo = bloqueo
            self.fin = bloqueo.fin_minimo
            self.error_fin = None
        finally:
            self.cargando = False
        self.notify_listeners()

    def set_fin(self, clave: str) -> None:
        self.fin = datetime.fromisoformat(clave)
        self.error_fin = None
        self.alerta = None
        self.notify_listeners()

    async def continuar(self) -> None:
        self.alerta = None
        if self.paso == PasoReserva.ELEGIR:
            if self.bloqueo is None:
                self.alerta = Alerta("Elige un cajón libre", "Toca un cajón marcado como libre.")
            else:
                self.paso = PasoReserva.HORARIO
        elif self.paso == PasoReserva.HORARIO and self.fin is not None:
            self.paso = PasoReserva.CONFIRMAR
        self.notify_listeners()

    async def confirmar(self) -> None:
        """Paso 3: crea la reserva (RF-05/RF-06) y la guarda en el teléfono (RNF-08)."""
        if self.cargando or self.bloqueo is None or self.fin is None:
            return
        self.alerta = None
        self.cargando = True
        self.notify_listeners()
        try:
            reserva = await asyncio.to_thread(
                self._reservas.crear_reserva,
                self.bloqueo.id_cajon,
                self.bloqueo.fecha_inicio,
                self.fin,
            )
        except ReservaError as e:
            self._error_al_crear(e)
        except ReservasNoDisponiblesError as e:
            logger.exception("Fallo al crear la reserva")
            self.alerta = alerta_no_disponible(e)
        else:
            # La tolerancia viene con el bloqueo (config_sistema); se guarda con la
            # reserva para la cuenta regresiva de "Mi reserva".
            self.reserva = replace(
                reserva,
                etiqueta=reserva.etiqueta or self.bloqueo.etiqueta,
                minutos_tolerancia=self.bloqueo.minutos_tolerancia,
            )
            reserva = self.reserva
            # El backend ya consumió el bloqueo: no hay nada que liberar.
            self.bloqueo = None
            usuario = self._auth.usuario_actual
            if usuario is not None:
                self._almacen.guardar(usuario.id_usuario, reserva)
            await llamar(self._al_reserva_creada)
        finally:
            self.cargando = False
        self.notify_listeners()

    async def regresar(self) -> None:
        if self.tiene_reserva_activa or self.paso == PasoReserva.ELEGIR:
            await self.cancelar()
            return
        # Volver de un paso a otro conserva el cajón apartado.
        self.paso = PasoReserva(self.paso - 1)
        self.alerta = None
        self.notify_listeners()

    async def cancelar(self) -> None:
        """Salir sin reservar: libera el cajón de inmediato (RF-03)."""
        self._soltar_bloqueo()
        await llamar(self._al_salir)

    async def ver_reserva(self) -> None:
        if self._al_ver_reserva is not None:
            await llamar(self._al_ver_reserva)

    # --- Internos ---

    def _reserva_guardada(self) -> ReservaCajon | None:
        """Reserva vigente guardada en el teléfono cuya tolerancia no ha vencido."""
        usuario = self._auth.usuario_actual
        reserva = self._almacen.leer(usuario.id_usuario) if usuario else None
        if reserva is None or not reserva.estado.vigente:
            return None
        limite = reserva.limite_tolerancia
        if limite is not None and datetime.now(UTC) >= limite:
            return None
        return reserva

    def _error_al_bloquear(self, e: ReservaError) -> None:
        if e.codigo == "RESERVA_ACTIVA":
            self.tiene_reserva_activa = True
        elif e.codigo == "NO_AUTENTICADO":
            self.alerta = ALERTA_SESION
        elif e.codigo == "FUERA_DE_HORARIO":
            self.alerta = Alerta("Fuera del horario de reservas", e.mensaje)
        else:
            self.alerta = Alerta("No se pudo apartar el cajón", e.mensaje)

    def _error_al_crear(self, e: ReservaError) -> None:
        if e.codigo in ERRORES_HORARIO:
            self.paso = PasoReserva.HORARIO
            self.error_fin = ERRORES_HORARIO[e.codigo]
            self.alerta = Alerta("No se puede reservar en este horario", e.mensaje)
        elif e.codigo in ERRORES_BLOQUEO:
            # El cajón ya no está apartado para este estudiante: se elige de nuevo.
            self.paso = PasoReserva.ELEGIR
            self.bloqueo = None
            self.fin = None
            self.alerta = Alerta(ERRORES_BLOQUEO[e.codigo], e.mensaje)
        elif e.codigo == "RESERVA_ACTIVA":
            self.bloqueo = None
            self.tiene_reserva_activa = True
        elif e.codigo == "NO_AUTENTICADO":
            self.alerta = ALERTA_SESION
        else:
            self.alerta = Alerta("No se pudo crear la reserva", e.mensaje)

    def _soltar_bloqueo(self) -> None:
        if self.bloqueo is None:
            return
        id_cajon, self.bloqueo = self.bloqueo.id_cajon, None
        # En segundo plano: salir de la pantalla no espera a la red. Si falla, el
        # barrido del backend lo libera al vencer bloqueo_ttl_s.
        try:
            tarea = asyncio.get_running_loop().create_task(self._liberar(id_cajon))
            _TAREAS.add(tarea)
            tarea.add_done_callback(_TAREAS.discard)
        except RuntimeError:
            logger.warning("Sin event loop: el cajón %s se liberará al vencer el bloqueo", id_cajon)

    async def _liberar(self, id_cajon: int) -> None:
        try:
            await asyncio.to_thread(self._reservas.liberar_bloqueo, id_cajon)
        except Exception:
            logger.exception("No se pudo liberar el cajón %s", id_cajon)
