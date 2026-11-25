"""Notificaciones push (FCM) del dispositivo, a través de la extensión `flet-fcm`.

El backend envía avisos de reserva (retraso, expiración, fin próximo…) a los tokens
registrados en `dispositivos_fcm`. Con la app cerrada o en segundo plano los muestra
el sistema; aquí solo se obtiene el token y se reciben los avisos que llegan con la app
abierta o que el usuario toca.

Todo es opcional: en PC, sin las variables de Firebase, sin permiso o sin la extensión
el servicio no hace nada y la app sigue funcionando con MQTT y consultas.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import flet as ft

from parking_app.core.config import ConfigFirebase

logger = logging.getLogger(__name__)

# Tipos de aviso que envía el backend (campo `tipo` del `data`).
TIPO_CONFLICTO_SENSOR = "conflicto_sensor"


@dataclass(frozen=True)
class AvisoPush:
    """Notificación recibida o tocada; el `data` del mensaje llega siempre como texto."""

    tipo: str | None = None
    id_reserva: str | None = None
    id_cajon: str | None = None
    titulo: str | None = None
    cuerpo: str | None = None

    @classmethod
    def desde(cls, titulo: Any, cuerpo: Any, datos: Any) -> "AvisoPush":
        datos = datos if isinstance(datos, dict) else {}

        def texto(valor: Any) -> str | None:
            return str(valor) if valor not in (None, "") else None

        return cls(
            tipo=texto(datos.get("tipo")),
            id_reserva=texto(datos.get("id_reserva")),
            id_cajon=texto(datos.get("id_cajon")),
            titulo=texto(titulo),
            cuerpo=texto(cuerpo),
        )

    @classmethod
    def desde_evento(cls, e: Any) -> "AvisoPush":
        return cls.desde(
            getattr(e, "titulo", None), getattr(e, "cuerpo", None), getattr(e, "datos", None)
        )

    @classmethod
    def desde_mapa(cls, m: dict[str, Any]) -> "AvisoPush":
        return cls.desde(m.get("titulo"), m.get("cuerpo"), m.get("datos"))


def _crear_fcm(**manejadores: Any) -> Any:
    """Crea el control Fcm; importa la extensión aquí para que sea opcional."""
    from flet_fcm import Fcm

    return Fcm(**manejadores)


class NotificacionesService:
    def __init__(
        self,
        config: ConfigFirebase | None,
        fabrica_fcm: Callable[..., Any] = _crear_fcm,
    ) -> None:
        self._config = config
        self._fabrica_fcm = fabrica_fcm
        self._fcm: Any = None
        self._al_renovar_token: Callable[[str], Awaitable[None] | None] | None = None
        self._al_mensaje: Callable[[AvisoPush], Awaitable[None] | None] | None = None
        self._al_tocar: Callable[[AvisoPush], Awaitable[None] | None] | None = None

    @staticmethod
    def soportada(page: ft.Page) -> bool:
        """Solo Android e iOS: en PC no hay FCM."""
        return page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)

    @property
    def activa(self) -> bool:
        return self._fcm is not None

    async def iniciar(
        self,
        page: ft.Page,
        al_renovar_token: Callable[[str], Awaitable[None] | None],
        al_mensaje: Callable[[AvisoPush], Awaitable[None] | None],
        al_tocar: Callable[[AvisoPush], Awaitable[None] | None],
    ) -> str | None:
        """Inicia Firebase, pide el permiso y devuelve el token del dispositivo.

        Devuelve None si las notificaciones no están disponibles; nunca lanza.
        Se puede llamar en cada inicio de sesión: Firebase y los oyentes se crean una vez.
        """
        if self._config is None or not self.soportada(page):
            return None
        try:
            if self._fcm is None:
                self._fcm = self._fabrica_fcm(
                    on_token_refresh=self._token_renovado,
                    on_message=self._mensaje_recibido,
                    on_message_opened=self._mensaje_tocado,
                )
            self._al_renovar_token = al_renovar_token
            self._al_mensaje = al_mensaje
            self._al_tocar = al_tocar
            c = self._config
            await self._fcm.inicializar(c.api_key, c.app_id, c.sender_id, c.project_id)
            if not await self._fcm.pedir_permiso():
                logger.info("El usuario no concedió el permiso de notificaciones")
                return None
            return await self._fcm.obtener_token() or None
        except Exception:
            logger.warning("No se pudieron activar las notificaciones push", exc_info=True)
            return None

    async def aviso_inicial(self) -> AvisoPush | None:
        """Notificación que abrió la app desde cerrada, si la hubo."""
        if self._fcm is None:
            return None
        try:
            mapa = await self._fcm.mensaje_inicial()
        except Exception:
            logger.warning("No se pudo leer la notificación inicial", exc_info=True)
            return None
        return AvisoPush.desde_mapa(mapa) if isinstance(mapa, dict) else None

    async def olvidar_token(self) -> None:
        """Invalida el token en Firebase (al cerrar sesión, tras borrarlo del servidor)."""
        if self._fcm is None:
            return
        try:
            await self._fcm.borrar_token()
        except Exception:
            logger.warning("No se pudo borrar el token de Firebase", exc_info=True)

    # --- Eventos de la extensión ---

    async def _token_renovado(self, e: Any) -> None:
        token = getattr(e, "token", "")
        if token and self._al_renovar_token is not None:
            await _llamar(self._al_renovar_token, token)

    async def _mensaje_recibido(self, e: Any) -> None:
        if self._al_mensaje is not None:
            await _llamar(self._al_mensaje, AvisoPush.desde_evento(e))

    async def _mensaje_tocado(self, e: Any) -> None:
        if self._al_tocar is not None:
            await _llamar(self._al_tocar, AvisoPush.desde_evento(e))


async def _llamar(callback: Callable[[Any], Awaitable[None] | None], valor: Any) -> None:
    # Un fallo de un callback no debe llegar a Flet (ni tumbar al resto de la app).
    try:
        resultado = callback(valor)
        if hasattr(resultado, "__await__"):
            await resultado
    except Exception:
        logger.exception("Falló el manejo de una notificación")
