import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum

from parking_app.core.observable import Observable
from parking_app.models.reserva_cajon import LlegadaRegistrada, ReglasReserva, ReservaCajon
from parking_app.models.usuario import MedioTransporte
from parking_app.services.lector_qr import LectorQr, es_codigo_del_sistema
from parking_app.services.reservas_service import (
    ReservaError,
    ReservasNoDisponiblesError,
    ReservasService,
)
from parking_app.viewmodels.alerta import Alerta
from parking_app.viewmodels.formato import hora_local, id_corto
from parking_app.viewmodels.navegacion import Navegar, llamar

logger = logging.getLogger(__name__)

TEXTOS_TRANSPORTE = {
    MedioTransporte.VEHICULO.value: "Automóvil",
    MedioTransporte.MOTOCICLETA.value: "Motocicleta",
}


class FaseEscaner(StrEnum):
    ESCANEANDO = "escaneando"
    VALIDANDO = "validando"
    RESULTADO = "resultado"


@dataclass(frozen=True)
class Resultado:
    valido: bool
    titulo: str
    subtitulo: str
    # Código válido: recuadro del cajón (etiqueta "C1", "Llegada registrada a las ...").
    cajon: tuple[str, str] | None = None
    # Código rechazado: (título del motivo, explicación).
    motivo: tuple[str, str] | None = None
    filas: list[tuple[str, str]] = field(default_factory=list)
    # Fila resaltada en verde (p. ej. "Cronómetro de uso iniciado").
    fila_destacada: str | None = None


RECHAZADO = ("Código rechazado", "No se registró ninguna llegada.")


def _horario(inicio, fin) -> str:
    return f"{hora_local(inicio)} a {hora_local(fin)}"


# Clase representativa de "Escanear QR" (administrador, Módulo C, RF-10/RF-11):
# lee el QR del estudiante con la cámara, lo valida con confirmar-llegada y
# muestra el resultado con el motivo del rechazo.
class EscanerViewModel(Observable):
    def __init__(
        self,
        reservas_service: ReservasService,
        al_regresar: Navegar,
        al_ver_reservas: Navegar,
        lector: LectorQr | None = None,
    ) -> None:
        super().__init__()
        self._reservas = reservas_service
        self._al_regresar = al_regresar
        self._al_ver_reservas = al_ver_reservas
        self._lector = lector or LectorQr()

        self.fase = FaseEscaner.ESCANEANDO
        self.resultado: Resultado | None = None
        self.linterna = False
        self.alerta: Alerta | None = None
        self._analizando = False
        self._validacion: asyncio.Task[None] | None = None
        self._reglas: ReglasReserva | None = None

    # --- Propiedades de presentación ---

    @property
    def titulo(self) -> str:
        return "Resultado" if self.fase == FaseEscaner.RESULTADO else "Escanear QR"

    @property
    def escaneando(self) -> bool:
        """La vista mantiene la cámara enviando cuadros solo en esta fase."""
        return self.fase == FaseEscaner.ESCANEANDO

    # --- Comandos de la cámara ---

    async def procesar_cuadro(self, imagen: bytes) -> None:
        """Un cuadro de la cámara. Se analiza uno a la vez; los demás se descartan."""
        if not self.escaneando or self._analizando:
            return
        self._analizando = True
        try:
            texto = await asyncio.to_thread(self._lector.leer, imagen)
        except Exception:
            logger.exception("Fallo al leer un cuadro")
            texto = None
        finally:
            self._analizando = False
        if texto and self.escaneando:
            await self.validar(texto)

    async def validar(self, codigo: str) -> None:
        """Valida un código leído (o escrito a mano en la PC, donde no hay cámara)."""
        codigo = codigo.strip()
        if not codigo or not self.escaneando:
            return
        self.alerta = None
        if not es_codigo_del_sistema(codigo):
            # Otro QR (un enlace, un producto...): ni siquiera se consulta al servidor.
            self._mostrar(Resultado(
                False, *RECHAZADO,
                motivo=("Código no reconocido",
                        "Este QR no es un código de reserva del estacionamiento."),
            ))
            return
        self.fase = FaseEscaner.VALIDANDO
        self.linterna = False
        self.notify_listeners()
        self._validacion = asyncio.get_running_loop().create_task(self._confirmar(codigo))
        try:
            await self._validacion
        except asyncio.CancelledError:
            pass
        finally:
            self._validacion = None

    def cancelar_validacion(self) -> None:
        """Deja de esperar al servidor y vuelve a escanear.

        Si el servidor alcanzó a registrar la llegada, al escanear de nuevo saldrá
        "Código ya utilizado": no se registra dos veces.
        """
        if self._validacion is not None:
            self._validacion.cancel()
        self.fase = FaseEscaner.ESCANEANDO
        self.notify_listeners()

    def alternar_linterna(self) -> None:
        self.linterna = not self.linterna
        self.notify_listeners()

    def error_camara(self, mensaje: str) -> None:
        self.alerta = Alerta("No se pudo usar la cámara", mensaje)
        self.linterna = False
        self.notify_listeners()

    # --- Navegación ---

    def escanear_otro(self) -> None:
        self.resultado = None
        self.alerta = None
        self.fase = FaseEscaner.ESCANEANDO
        self.notify_listeners()

    async def ver_reservas(self) -> None:
        await llamar(self._al_ver_reservas)

    async def regresar(self) -> None:
        if self.fase == FaseEscaner.VALIDANDO:
            self.cancelar_validacion()
            return
        await llamar(self._al_regresar)

    # --- Internos ---

    async def _confirmar(self, codigo: str) -> None:
        try:
            llegada = await asyncio.to_thread(self._reservas.confirmar_llegada, codigo)
        except ReservaError as e:
            resultado = await self._rechazo(codigo, e)
        except ReservasNoDisponiblesError as e:
            logger.warning("No se pudo validar el código: %s", e)
            resultado = Resultado(
                False, "No se pudo validar",
                "No hubo respuesta del servidor." if e.sin_red else
                "El servicio de reservas no está disponible.",
                motivo=("Vuelve a escanear el código",
                        "Si la llegada sí se registró, el código aparecerá como «ya utilizado»."),
            )
        else:
            resultado = await self._aceptado(llegada)
        self._mostrar(resultado)

    async def _aceptado(self, llegada: LlegadaRegistrada) -> Resultado:
        # La respuesta no trae la hora de inicio: se lee la reserva (RLS de administrador).
        horario = "—"
        try:
            reserva = await asyncio.to_thread(self._reservas.obtener_reserva, llegada.id_reserva)
            if reserva is not None:
                horario = _horario(reserva.fecha_inicio, reserva.fecha_fin)
        except (ReservaError, ReservasNoDisponiblesError):
            logger.warning("No se pudo leer el horario de la reserva", exc_info=True)
        return Resultado(
            True, "Código válido", "Se registró la llegada del estudiante.",
            cajon=(llegada.etiqueta,
                   f"Llegada registrada a las {hora_local(llegada.fecha_llegada)}"),
            filas=[
                ("Reserva", id_corto(llegada.id_reserva)),
                ("Horario reservado", horario),
                ("Medio de transporte",
                 TEXTOS_TRANSPORTE.get(llegada.medio_transporte or "", "Sin registrar")),
                ("Estado", "Cronómetro de uso iniciado"),
            ],
            fila_destacada="Estado",
        )

    async def _rechazo(self, codigo: str, e: ReservaError) -> Resultado:
        if e.codigo == "NO_AUTENTICADO":
            return Resultado(False, *RECHAZADO, motivo=(
                "Tu sesión expiró", "Cierra sesión y vuelve a entrar para validar códigos."))
        if e.codigo == "NO_AUTORIZADO":
            return Resultado(False, *RECHAZADO, motivo=("Sin permiso", e.mensaje))
        if e.codigo == "QR_INVALIDO":
            return Resultado(False, *RECHAZADO, motivo=(
                "Código no reconocido", "El código no corresponde a ninguna reserva."))

        reserva = await self._buscar(codigo)
        filas = []
        if reserva is not None:
            filas = [("Reserva", id_corto(reserva.id_reserva)), ("Cajón", reserva.etiqueta_cajon)]

        if e.codigo == "QR_EXPIRADO":
            tolerancia = await self._minutos_tolerancia()
            texto = ("El estudiante no llegó dentro del tiempo de llegada y la tolerancia"
                     + (f" de {tolerancia} minutos." if tolerancia else ".")
                     + " La reserva se canceló.")
            if reserva is not None and reserva.cronometro and tolerancia:
                expiro = reserva.cronometro + timedelta(minutes=tolerancia)
                filas.append(("Expiró a las", hora_local(expiro)))
            return Resultado(False, *RECHAZADO, motivo=("Código expirado", texto), filas=filas)
        if e.codigo == "QR_USADO":
            if reserva is not None and reserva.fecha_llegada:
                filas.append(("Llegada registrada", hora_local(reserva.fecha_llegada)))
            return Resultado(False, *RECHAZADO, filas=filas, motivo=(
                "Código ya utilizado",
                "Este código ya se usó para registrar una llegada. Cada código sirve una sola vez."))
        if e.codigo == "QR_CANCELADO":
            # La base no guarda la hora de cancelación: se muestra el horario reservado.
            if reserva is not None:
                filas.append(("Horario reservado",
                              _horario(reserva.fecha_inicio, reserva.fecha_fin)))
            return Resultado(False, *RECHAZADO, filas=filas, motivo=(
                "Reserva cancelada",
                "El estudiante canceló esta reserva antes de llegar, por lo que el código ya no "
                "es válido."))
        return Resultado(False, *RECHAZADO, motivo=("No se pudo registrar la llegada", e.mensaje),
                         filas=filas)

    async def _buscar(self, codigo: str) -> ReservaCajon | None:
        try:
            return await asyncio.to_thread(self._reservas.reserva_por_codigo, codigo)
        except (ReservaError, ReservasNoDisponiblesError):
            logger.warning("No se pudieron leer los datos del código rechazado", exc_info=True)
            return None

    async def _minutos_tolerancia(self) -> int | None:
        if self._reglas is None:
            try:
                self._reglas = await asyncio.to_thread(self._reservas.reglas)
            except (ReservaError, ReservasNoDisponiblesError):
                return None
        return self._reglas.minutos_tolerancia

    def _mostrar(self, resultado: Resultado) -> None:
        self.resultado = resultado
        self.fase = FaseEscaner.RESULTADO
        self.linterna = False
        self.notify_listeners()
