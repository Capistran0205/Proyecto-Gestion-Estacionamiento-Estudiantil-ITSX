"""Suscripción MQTT al tópico de ocupación con las credenciales del usuario.

paho corre su propio hilo de red: los callbacks `al_recibir` y
`al_cambiar_estado` se invocan desde ese hilo, así que quien los reciba debe
reenviarlos a su event loop (el ViewModel usa `call_soon_threadsafe`).
"""

import logging
import ssl
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import certifi
import paho.mqtt.client as mqtt

from parking_app.core.config import ConfigMqtt
from parking_app.models.evento_ocupacion import EventoOcupacion, PayloadInvalidoError

logger = logging.getLogger(__name__)

# Códigos CONNACK (MQTT 5 / equivalentes de 3.1.1) por credenciales rechazadas.
_RC_CREDENCIALES = {134, 135}  # Bad user name or password, Not authorized
PUERTOS_SIN_TLS = {1883}

# Clase representativa para los diversos estados de conexión con EMQX.
class EstadoConexion(StrEnum):
    CONECTANDO = "conectando"
    CONECTADO = "conectado"
    RECONECTANDO = "reconectando"
    CREDENCIALES_INVALIDAS = "credenciales_invalidas"
    DESCONECTADO = "desconectado"


AlRecibir = Callable[[EventoOcupacion], None]
AlCambiarEstado = Callable[[EstadoConexion], None]

# Clase representativa para abrir la conexión a EMQX mediante paho usando las credenciales del usuario, con TLS verificado mediante certifi
# es capaz de establecer reconexión automática de 1 a 30 segundos y con suscripción establecida de tipo  QoS 1.
# También se encarga de cerra la conexión a EMQX
class MqttService:
    def __init__(
        self,
        config_factory: Callable[[], ConfigMqtt] | None = None,
        cliente_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if config_factory is None:
            from parking_app.core.config import get_settings

            config_factory = lambda: get_settings().mqtt()  # noqa: E731
        self._config_factory = config_factory
        self._cliente_factory = cliente_factory or (
            lambda client_id: mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        )
        self._cliente: Any = None
        self._topico = ""
        self._cerrando = False
        self._al_recibir: AlRecibir = lambda _: None
        self._al_cambiar_estado: AlCambiarEstado = lambda _: None

    def conectar(
        self,
        usuario: str,
        password: str,
        al_recibir: AlRecibir,
        al_cambiar_estado: AlCambiarEstado,
    ) -> None:
        """Conecta en segundo plano; paho reintenta solo si se pierde la conexión."""
        self.desconectar()
        config = self._config_factory()
        self._topico = config.topico_ocupacion
        self._al_recibir = al_recibir
        self._al_cambiar_estado = al_cambiar_estado
        self._cerrando = False

        cliente = self._cliente_factory(f"app-{uuid.uuid4().hex[:12]}")
        cliente.username_pw_set(usuario, password)
        if config.port not in PUERTOS_SIN_TLS:
            # CA de certifi: en Android el Python embebido no trae almacén de certificados.
            cliente.tls_set(ca_certs=certifi.where(), cert_reqs=ssl.CERT_REQUIRED)
        cliente.reconnect_delay_set(min_delay=1, max_delay=30)
        cliente.on_connect = self._on_connect
        cliente.on_disconnect = self._on_disconnect
        cliente.on_message = self._on_message
        self._cliente = cliente

        self._notificar(EstadoConexion.CONECTANDO)
        cliente.connect_async(config.host, config.port, keepalive=30)
        cliente.loop_start()

    def desconectar(self) -> None:
        cliente, self._cliente = self._cliente, None
        if cliente is None:
            return
        self._cerrando = True
        try:
            cliente.disconnect()
            cliente.loop_stop()
        except Exception:
            logger.warning("Error al cerrar la conexión MQTT", exc_info=True)
        self._notificar(EstadoConexion.DESCONECTADO)

    # --- Callbacks de paho (hilo de red) ---

    def _on_connect(self, cliente, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code.is_failure:
            if getattr(reason_code, "value", None) in _RC_CREDENCIALES:
                logger.error("El broker rechazó las credenciales MQTT: %s", reason_code)
                # Reintentar con las mismas credenciales no sirve: se detiene.
                self._cerrando = True
                cliente.disconnect()
                self._notificar(EstadoConexion.CREDENCIALES_INVALIDAS)
            else:
                logger.warning("Conexión MQTT rechazada: %s", reason_code)
                self._notificar(EstadoConexion.RECONECTANDO)
            return
        cliente.subscribe(self._topico, qos=1)
        self._notificar(EstadoConexion.CONECTADO)

    def _on_disconnect(self, _cliente, _userdata, _flags, reason_code, _properties=None) -> None:
        if self._cerrando:
            # Desconexión pedida por nosotros: el estado ya se notificó.
            return
        logger.warning("Conexión MQTT perdida (%s); reintentando", reason_code)
        self._notificar(EstadoConexion.RECONECTANDO)

    def _on_message(self, _cliente, _userdata, mensaje) -> None:
        # Un mensaje malformado de un nodo no debe afectar al resto.
        try:
            evento = EventoOcupacion.from_payload(mensaje.payload)
        except PayloadInvalidoError as e:
            logger.warning("Mensaje MQTT ignorado: %s", e)
            return
        try:
            self._al_recibir(evento)
        except Exception:
            logger.exception("Error al procesar el evento de %s", evento.etiqueta_cajon)

    def _notificar(self, estado: EstadoConexion) -> None:
        try:
            self._al_cambiar_estado(estado)
        except Exception:
            logger.exception("Error al notificar el estado MQTT %s", estado)
