import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from parking_app.core.config import NUM_CAJONES
from parking_app.core.observable import Observable
from parking_app.models.cajon_estacionamiento import EstadoCajon, etiqueta_de_modulo
from parking_app.models.evento_ocupacion import EventoOcupacion
from parking_app.services.auth_service import AuthService, CredencialesMqtt
from parking_app.services.cajones_service import CajonesService
from parking_app.services.emqx_admin_service import EmqxAdminService
from parking_app.services.mqtt_service import EstadoConexion, MqttService
from parking_app.viewmodels.navegacion import Navegar, llamar

logger = logging.getLogger(__name__)

TIMEOUT_SNAPSHOT_SEGUNDOS = 5

TEXTOS_ESTADO = {
    EstadoCajon.LIBRE: "Libre",
    EstadoCajon.OCUPADO: "Ocupado",
    EstadoCajon.RESERVADO: "Reservado",
    EstadoCajon.NO_CONECTADO: "No conectado",
}

TEXTOS_CONEXION = {
    EstadoConexion.CONECTANDO: "Conectando…",
    EstadoConexion.CONECTADO: "En vivo",
    EstadoConexion.RECONECTANDO: "Reconectando…",
    EstadoConexion.CREDENCIALES_INVALIDAS: "Sin acceso",
    EstadoConexion.DESCONECTADO: "Sin conexión",
}

# Clase como Enum de cadenas para representar/traducir los niveles de ocupación del estacionamiento
class NivelDisponibilidad(StrEnum):
    ALTA = "alta"
    MEDIA = "media"
    LLENO = "nula"
    SIN_DATOS = "sin datos"

# Clase para mostrar los datos de un cajón de estacionamiento, incluyendo su etiqueta, el estado actual y 
# un texto representativo del estado actual.
@dataclass(frozen=True)
class CajonVista:
    etiqueta: str
    estado: EstadoCajon
    texto_estado: str


class OcupacionViewModel(Observable):
    def __init__(
        self,
        auth_service: AuthService,
        cajones_service: CajonesService,
        mqtt_service: MqttService,
        emqx_service: EmqxAdminService,
        timeout_nodo_segundos: int,
        al_ir_a_inicio: Navegar,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self._cajones = cajones_service
        self._mqtt = mqtt_service
        self._emqx = emqx_service
        self._timeout_nodo = timeout_nodo_segundos
        self._al_ir_a_inicio = al_ir_a_inicio
        self._reloj = reloj

        etiquetas = [etiqueta_de_modulo(i) for i in range(1, NUM_CAJONES + 1)]
        self._estados: dict[str, EstadoCajon] = dict.fromkeys(etiquetas, EstadoCajon.NO_CONECTADO)
        # Plazo de cada nodo para el timeout de "no conectado".
        self._ultimo_reporte: dict[str, float] = {}
        # Cajones con al menos un evento MQTT (el snapshot ya no los pisa).
        self._con_evento: set[str] = set()
        self._ultima_actualizacion: float | None = None
        self.estado_conexion = EstadoConexion.CONECTANDO
        self.cargando = True
        self.error_snapshot = False

        self._loop: asyncio.AbstractEventLoop | None = None
        self._tarea_reloj: asyncio.Task[None] | None = None
        # Un solo intento por sesión de reparar la credencial en EMQX.
        self._sincronizacion_intentada = False
        self._tarea_sincronizacion: asyncio.Task[None] | None = None

    # --- Propiedades de presentación ---

    @property
    def cajones(self) -> list[CajonVista]:
        return [
            CajonVista(etiqueta, estado, TEXTOS_ESTADO[estado])
            for etiqueta, estado in self._estados.items()
        ]

    def _contar(self, estado: EstadoCajon) -> int:
        return sum(e == estado for e in self._estados.values())

    @property
    def total(self) -> int:
        return len(self._estados)

    @property
    def libres(self) -> int:
        return self._contar(EstadoCajon.LIBRE)

    @property
    def ocupados(self) -> int:
        return self._contar(EstadoCajon.OCUPADO)

    @property
    def reservados(self) -> int:
        return self._contar(EstadoCajon.RESERVADO)

    @property
    def con_datos(self) -> int:
        """Cajones cuyo estado se conoce (no "no conectado")."""
        return self.total - self._contar(EstadoCajon.NO_CONECTADO)

    @property
    def porcentaje_ocupado(self) -> int:
        """Ocupados + reservados sobre los cajones con datos (0 si no hay datos)."""
        if self.con_datos == 0:
            return 0
        return round(100 * (self.ocupados + self.reservados) / self.con_datos)

    @property
    def nivel_disponibilidad(self) -> NivelDisponibilidad:
        if self.con_datos == 0:
            return NivelDisponibilidad.SIN_DATOS
        if self.porcentaje_ocupado < 50:
            return NivelDisponibilidad.ALTA
        if self.porcentaje_ocupado < 100:
            return NivelDisponibilidad.MEDIA
        return NivelDisponibilidad.LLENO

    @property
    def texto_disponibilidad(self) -> str:
        nivel = self.nivel_disponibilidad
        if nivel == NivelDisponibilidad.SIN_DATOS:
            return "Sin datos de los sensores"
        return f"Disponibilidad {nivel.value} — {self.porcentaje_ocupado}% ocupado"

    @property
    def texto_libres(self) -> str:
        return f"{self.libres} de {self.total} cajones libres"

    @property
    def en_vivo(self) -> bool:
        return self.estado_conexion == EstadoConexion.CONECTADO

    @property
    def texto_conexion(self) -> str:
        return TEXTOS_CONEXION[self.estado_conexion]

    @property
    def texto_actualizado(self) -> str:
        if self.estado_conexion == EstadoConexion.CREDENCIALES_INVALIDAS:
            return "No se pudo acceder al servidor de sensores"
        if self._ultima_actualizacion is None:
            if self.error_snapshot:
                return "Esperando datos de los sensores…"
            return "Cargando estado del estacionamiento…"
        segundos = int(self._reloj() - self._ultima_actualizacion)
        if segundos < 5:
            return "Actualizado hace un momento"
        if segundos < 60:
            return f"Actualizado hace {segundos} segundos"
        minutos = segundos // 60
        if minutos < 60:
            return f"Actualizado hace {minutos} {'minuto' if minutos == 1 else 'minutos'}"
        return "Actualizado hace más de una hora"

    # --- Ciclo de vida ---

    async def iniciar(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._tarea_reloj = self._loop.create_task(self._tic())
        self._conectar_mqtt()
        await self._cargar_snapshot()

    def detener(self) -> None:
        if self._tarea_reloj is not None:
            self._tarea_reloj.cancel()
            self._tarea_reloj = None
        if self._tarea_sincronizacion is not None:
            self._tarea_sincronizacion.cancel()
            self._tarea_sincronizacion = None
        self._mqtt.desconectar()
        self._loop = None

    async def ir_a_inicio(self) -> None:
        await llamar(self._al_ir_a_inicio)

    # --- Internos ---

    async def _cargar_snapshot(self) -> None:
        try:
            cajones = await asyncio.wait_for(
                asyncio.to_thread(self._cajones.obtener_estado_actual),
                timeout=TIMEOUT_SNAPSHOT_SEGUNDOS,
            )
        except Exception:
            # Sin snapshot la vista sigue: MQTT irá llenando cada cajón.
            logger.exception("No se pudo cargar el estado inicial de los cajones")
            self.error_snapshot = True
        else:
            for cajon in cajones:
                # Un evento MQTT que llegó antes que el snapshot es más reciente.
                if cajon.etiqueta in self._estados and cajon.etiqueta not in self._con_evento:
                    self._estados[cajon.etiqueta] = cajon.estado_actual
            self._ultima_actualizacion = self._ultima_actualizacion or self._reloj()
        finally:
            self.cargando = False
        self.notify_listeners()

    def _conectar_mqtt(self) -> None:
        credenciales = self._auth.credenciales_mqtt
        if credenciales is None:
            logger.error("Sin credenciales MQTT en memoria; no hay sesión activa")
            self.estado_conexion = EstadoConexion.CREDENCIALES_INVALIDAS
            return
        try:
            self._mqtt.conectar(
                credenciales.usuario,
                credenciales.password,
                al_recibir=lambda evento: self._en_loop(self._recibir_evento, evento),
                al_cambiar_estado=lambda estado: self._en_loop(self._cambiar_estado, estado),
            )
        except Exception:
            logger.exception("No se pudo iniciar la conexión MQTT")
            self._auth.descartar_password_mqtt()
            self.estado_conexion = EstadoConexion.DESCONECTADO

    def _en_loop(self, funcion: Callable[..., None], *args: object) -> None:
        """Reenvía un callback del hilo de paho al event loop de la UI."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(funcion, *args)

    def _recibir_evento(self, evento: EventoOcupacion) -> None:
        ahora = self._reloj()
        self._estados[evento.etiqueta_cajon] = evento.estado
        self._ultimo_reporte[evento.etiqueta_cajon] = ahora
        self._con_evento.add(evento.etiqueta_cajon)
        self._ultima_actualizacion = ahora
        self.notify_listeners()

    def _cambiar_estado(self, estado: EstadoConexion) -> None:
        if estado == EstadoConexion.CONECTADO:
            # El plazo de cada nodo cuenta desde que hay conexión (también al
            # reconectar: mientras no había conexión no pudo llegar nada).
            ahora = self._reloj()
            for etiqueta in self._estados:
                self._ultimo_reporte[etiqueta] = ahora
            # El broker aceptó la contraseña: ya no hace falta en memoria.
            self._auth.descartar_password_mqtt()
        elif estado == EstadoConexion.CREDENCIALES_INVALIDAS:
            if self._iniciar_sincronizacion():
                # Se repara la credencial en EMQX y se reconecta.
                estado = EstadoConexion.CONECTANDO
            else:
                self._auth.descartar_password_mqtt()
        self.estado_conexion = estado
        self.notify_listeners()

    def _iniciar_sincronizacion(self) -> bool:
        """Lanza la resincronización con EMQX si aún procede; True si se lanzó.

        EMQX puede tener otra contraseña (falló su actualización al restablecerla)
        o ni siquiera el usuario (falló su alta al registrarse). Solo se intenta una
        vez y solo con la contraseña del login, que Supabase acaba de aceptar y por
        tanto es la vigente: nunca una antigua que haría retroceder a EMQX.
        """
        credenciales = self._auth.credenciales_mqtt
        if self._sincronizacion_intentada or credenciales is None or self._loop is None:
            return False
        self._sincronizacion_intentada = True
        self._tarea_sincronizacion = self._loop.create_task(
            self._sincronizar_y_reconectar(credenciales)
        )
        return True

    async def _sincronizar_y_reconectar(self, credenciales: CredencialesMqtt) -> None:
        logger.warning(
            "El broker rechazó la credencial MQTT de %s; se resincroniza con EMQX",
            credenciales.usuario,
        )
        try:
            await asyncio.to_thread(
                self._emqx.crear_credencial, credenciales.usuario, credenciales.password
            )
        except Exception:
            logger.exception("No se pudo resincronizar la credencial MQTT de %s", credenciales.usuario)
            # Sin más intentos: muestra "Sin acceso" y descarta la contraseña.
            self._cambiar_estado(EstadoConexion.CREDENCIALES_INVALIDAS)
            return
        logger.info("Credencial MQTT de %s resincronizada; reconectando", credenciales.usuario)
        # Si el broker vuelve a rechazarla, _cambiar_estado ya no reintenta.
        self._conectar_mqtt()

    def _revisar_nodos(self) -> None:
        # Solo con conexión activa: si la app está desconectada, la falta de
        # mensajes no dice nada de los nodos (lo indica la píldora de estado).
        if self.estado_conexion != EstadoConexion.CONECTADO or self._timeout_nodo <= 0:
            return
        ahora = self._reloj()
        for etiqueta, ultimo in self._ultimo_reporte.items():
            if ahora - ultimo > self._timeout_nodo:
                self._estados[etiqueta] = EstadoCajon.NO_CONECTADO

    async def _tic(self) -> None:
        while True:
            await asyncio.sleep(1)
            self._revisar_nodos()
            self.notify_listeners()
