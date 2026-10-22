"""Alta de credenciales MQTT en EMQX (API REST v5, base de datos interna).

Cada estudiante usa su propia cuenta en el broker (usuario = correo
institucional) con ACL de **solo suscripción** al tópico de ocupación y a los
subtópicos de reservas (`reserva1/+`).
"""

import logging
from collections.abc import Callable, Iterable, Iterator
from typing import Any
from urllib.parse import quote

import httpx

from parking_app.core.config import DOMINIOS_CORREO_PERMITIDOS, ConfigEmqx

logger = logging.getLogger(__name__)

RUTA_USUARIOS = "/authentication/password_based:built_in_database/users"
RUTA_ACL_USUARIOS = "/authorization/sources/built_in_database/rules/users"


class EmqxError(Exception):
    """Falla al aprovisionar la credencial en EMQX."""

Regla = dict[str, str]


# Clase representativa que crea las credenciales en EMQX del usuario previamente registrado
# asigna una ACL que solo le permite suscribirse al tópico de ocupación de cajones de estacionamiento
# públicado por el ESP32 y a los subtópicos de reservas publicados por el backend.
class EmqxAdminService:
    def __init__(
        self,
        config_factory: Callable[[], ConfigEmqx] | None = None,
        topicos_factory: Callable[[], list[str]] | None = None,
        transporte: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        if config_factory is None or topicos_factory is None:
            from parking_app.core.config import get_settings

            config_factory = config_factory or (lambda: get_settings().emqx())
            topicos_factory = topicos_factory or (lambda: get_settings().topicos_suscripcion())
        self._config_factory = config_factory
        self._topicos_factory = topicos_factory
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
            self._asignar_acl(cliente, correo, self.reglas_estudiante())
        logger.info("Credencial MQTT aprovisionada para %s", correo)

    def actualizar_password(self, correo: str, nueva: str) -> None:
        """Mantiene la contraseña MQTT igual a la de la cuenta tras restablecerla."""
        with self._cliente() as cliente:
            r = cliente.put(f"{RUTA_USUARIOS}/{_id(correo)}", json={"password": nueva})
            _verificar(r, "actualizar contraseña MQTT")

    def reglas_estudiante(self) -> list[Regla]:
        # EMQX evalúa en orden: se permite suscribirse a los tópicos y se niega todo
        # lo demás (sin la regla de deny aplicaría `no_match`, que por defecto es allow).
        return [
            *({"topic": t, "permission": "allow", "action": "subscribe"} for t in self._topicos_factory()),
            {"topic": "#", "permission": "deny", "action": "all"},
        ]

    # --- Migración de ACL (scripts/migrar_acl_emqx.py) ---

    def listar_acl(self, por_pagina: int = 100) -> Iterator[dict[str, Any]]:
        """Recorre todas las páginas de ACL por usuario: {"username", "rules"}."""
        with self._cliente() as cliente:
            pagina = 1
            while True:
                r = cliente.get(RUTA_ACL_USUARIOS, params={"page": pagina, "limit": por_pagina})
                _verificar(r, "listar ACL MQTT")
                cuerpo = r.json()
                yield from cuerpo.get("data", [])
                if not cuerpo.get("meta", {}).get("hasnext"):
                    return
                pagina += 1

    def reemplazar_acl(self, usuario: str, reglas: list[Regla]) -> None:
        with self._cliente() as cliente:
            self._asignar_acl(cliente, usuario, reglas)

    def _asignar_acl(self, cliente: httpx.Client, usuario: str, reglas: list[Regla]) -> None:
        r = cliente.post(RUTA_ACL_USUARIOS, json=[{"username": usuario, "rules": reglas}])
        if r.status_code == 409:
            r = cliente.put(
                f"{RUTA_ACL_USUARIOS}/{_id(usuario)}",
                json={"username": usuario, "rules": reglas},
            )
        _verificar(r, "asignar ACL MQTT")

    def _cliente(self) -> httpx.Client:
        config = self._config_factory()
        return httpx.Client(
            base_url=_base_api(config.api_url),
            auth=(config.api_key, config.api_secret),
            timeout=self._timeout,
            transport=self._transporte,
        )


def planear_migracion_acl(
    acl: Iterable[dict[str, Any]],
    reglas_estudiante: list[Regla],
    topico_sistema: str,
    usuarios_esp32: Iterable[str] = (),
) -> list[tuple[str, list[Regla]]]:
    """Qué ACL cambiar para dar acceso a `reserva1/+` (usuario, reglas nuevas).

    - Estudiante (correo institucional): se le asigna el ACL estándar completo.
    - ESP32 (indicada por nombre): se antepone el permiso de suscripción y se
      conservan sus demás reglas (p. ej. publicar en el tópico de ocupación).
    - Cualquier otra cuenta no se toca.
    """
    esp32 = set(usuarios_esp32)
    regla_sistema: Regla = {"topic": topico_sistema, "permission": "allow", "action": "subscribe"}
    cambios = []
    for entrada in acl:
        usuario = entrada.get("username", "")
        originales = entrada.get("rules", [])
        reglas = _normalizar(originales)
        if usuario in esp32:
            if regla_sistema not in reglas:
                # Se conservan las reglas tal como vienen (qos, retain...), solo se antepone la nueva.
                cambios.append((usuario, [regla_sistema, *originales]))
        elif usuario.lower().endswith(tuple(f"@{d}" for d in DOMINIOS_CORREO_PERMITIDOS)):
            if reglas != reglas_estudiante:
                cambios.append((usuario, reglas_estudiante))
    return cambios


def _normalizar(reglas: list[dict[str, Any]]) -> list[Regla]:
    # La API puede devolver campos extra (qos, retain); solo se comparan los que se asignan.
    return [{k: str(r[k]) for k in ("topic", "permission", "action") if k in r} for r in reglas]


def _base_api(url: str) -> str:
    url = url.rstrip("/")
    return url if "/api/v" in url else f"{url}/api/v5"


def _id(correo: str) -> str:
    return quote(correo, safe="")


def _verificar(respuesta: httpx.Response, accion: str) -> None:
    if respuesta.is_success:
        return
    raise EmqxError(f"No se pudo {accion}: HTTP {respuesta.status_code} {respuesta.text[:200]}")
