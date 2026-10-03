"""Alta de credenciales MQTT en EMQX (API REST v5, base de datos interna).

Cada estudiante usa su propia cuenta en el broker (usuario = correo
institucional) con ACL de **solo suscripción** al tópico de ocupación.
"""

import logging
from collections.abc import Callable
from urllib.parse import quote

import httpx

from parking_app.core.config import ConfigEmqx

logger = logging.getLogger(__name__)

RUTA_USUARIOS = "/authentication/password_based:built_in_database/users"
RUTA_ACL_USUARIOS = "/authorization/sources/built_in_database/rules/users"


class EmqxError(Exception):
    """Falla al aprovisionar la credencial en EMQX."""

# Clase representativa que crea las credenciales en EMQX del usuario previamente registrado
# asigna una ACL que solo le permite suscribirse al tópico de ocupación de cajones de estacionamiento públicado por el ESP32.
class EmqxAdminService:
    def __init__(
        self,
        config_factory: Callable[[], ConfigEmqx] | None = None,
        topico_factory: Callable[[], str] | None = None,
        transporte: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        if config_factory is None or topico_factory is None:
            from parking_app.core.config import get_settings

            config_factory = config_factory or (lambda: get_settings().emqx())
            topico_factory = topico_factory or (lambda: get_settings().mqtt_topic_ocupacion)
        self._config_factory = config_factory
        self._topico_factory = topico_factory
        self._transporte = transporte
        self._timeout = timeout

    def crear_credencial(self, correo: str, contraseña: str) -> None:
        """Crea (o actualiza) el usuario MQTT y le asigna el ACL de solo suscripción."""
        with self._cliente() as cliente:
            r = cliente.post(
                RUTA_USUARIOS,
                json={"user_id": correo, "password": contraseña, "is_superuser": False},
            )
            if r.status_code == 409:
                # Ya existía (p. ej. un registro previo que falló a la mitad).
                r = cliente.put(
                    f"{RUTA_USUARIOS}/{_id(correo)}",
                    json={"password": contraseña, "is_superuser": False},
                )
            _verificar(r, "crear usuario MQTT")

            reglas = self._reglas_solo_suscripcion()
            r = cliente.post(RUTA_ACL_USUARIOS, json=[{"username": correo, "rules": reglas}])
            if r.status_code == 409:
                r = cliente.put(
                    f"{RUTA_ACL_USUARIOS}/{_id(correo)}",
                    json={"username": correo, "rules": reglas},
                )
            _verificar(r, "asignar ACL MQTT")
        logger.info("Credencial MQTT aprovisionada para %s", correo)

    def actualizar_password(self, correo: str, nueva: str) -> None:
        """Mantiene la contraseña MQTT igual a la de la cuenta tras restablecerla."""
        with self._cliente() as cliente:
            r = cliente.put(f"{RUTA_USUARIOS}/{_id(correo)}", json={"password": nueva})
            _verificar(r, "actualizar contraseña MQTT")

    def _reglas_solo_suscripcion(self) -> list[dict[str, str]]:
        # EMQX evalúa en orden: se permite suscribirse al tópico y se niega todo
        # lo demás (sin la regla de deny aplicaría `no_match`, que por defecto es allow).
        return [
            {"topic": self._topico_factory(), "permission": "allow", "action": "subscribe"},
            {"topic": "#", "permission": "deny", "action": "all"},
        ]

    def _cliente(self) -> httpx.Client:
        config = self._config_factory()
        return httpx.Client(
            base_url=_base_api(config.api_url),
            auth=(config.api_key, config.api_secret),
            timeout=self._timeout,
            transport=self._transporte,
        )


def _base_api(url: str) -> str:
    url = url.rstrip("/")
    return url if "/api/v" in url else f"{url}/api/v5"


def _id(correo: str) -> str:
    return quote(correo, safe="")


def _verificar(respuesta: httpx.Response, accion: str) -> None:
    if respuesta.is_success:
        return
    raise EmqxError(f"No se pudo {accion}: HTTP {respuesta.status_code} {respuesta.text[:200]}")
