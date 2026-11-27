from dataclasses import dataclass, field
from typing import Any, Optional

import flet as ft

__all__ = ["Fcm", "FcmMensajeEvent", "FcmTokenEvent"]


@dataclass
class FcmTokenEvent(ft.Event["Fcm"]):
    """Firebase entregó un token nuevo para este dispositivo."""

    token: str = ""


@dataclass
class FcmMensajeEvent(ft.Event["Fcm"]):
    """Notificación recibida (app abierta) o tocada (app en segundo plano o cerrada)."""

    titulo: Optional[str] = None
    cuerpo: Optional[str] = None
    # `data` del mensaje: todos los valores llegan como texto.
    datos: dict[str, Any] = field(default_factory=dict)


@ft.control("Fcm")
class Fcm(ft.Service):
    """Firebase Cloud Messaging (solo Android e iOS).

    Firebase se inicia desde código con los datos de `google-services.json`, así no
    hace falta el plugin de Gradle (el proyecto que genera `flet build` no lo trae).
    Con la app cerrada o en segundo plano el sistema muestra las notificaciones que
    traen el bloque `notification`; esta extensión solo avisa de las que llegan con
    la app abierta y de las que el usuario toca.
    """

    on_token_refresh: Optional[ft.EventHandler[FcmTokenEvent]] = None
    """El token del dispositivo cambió: hay que registrarlo de nuevo."""

    on_message: Optional[ft.EventHandler[FcmMensajeEvent]] = None
    """Llegó una notificación con la app abierta (el sistema no la muestra)."""

    on_message_opened: Optional[ft.EventHandler[FcmMensajeEvent]] = None
    """El usuario tocó una notificación con la app en segundo plano."""

    def before_update(self):
        super().before_update()
        if self.page.web or self.page.platform not in (
            ft.PagePlatform.ANDROID,
            ft.PagePlatform.IOS,
        ):
            raise ft.FletUnsupportedPlatformException(
                "Fcm solo funciona en Android e iOS."
            )

    async def inicializar(
        self, api_key: str, app_id: str, sender_id: str, project_id: str
    ) -> None:
        """Inicia Firebase con los datos de `google-services.json`.

        Args:
            api_key: `current_key` de `api_key`.
            app_id: `mobilesdk_app_id` de `client_info`.
            sender_id: `project_number` de `project_info`.
            project_id: `project_id` de `project_info`.
        """
        await self._invoke_method(
            "inicializar",
            {
                "api_key": api_key,
                "app_id": app_id,
                "sender_id": sender_id,
                "project_id": project_id,
            },
        )

    async def pedir_permiso(self) -> bool:
        """Pide permiso para mostrar notificaciones (Android 13+). `True` si se concedió."""
        return bool(await self._invoke_method("pedir_permiso"))

    async def obtener_token(self) -> Optional[str]:
        """Token FCM de este dispositivo; `None` si todavía no se puede obtener."""
        return await self._invoke_method("obtener_token")

    async def borrar_token(self) -> None:
        """Invalida el token actual (al cerrar sesión)."""
        await self._invoke_method("borrar_token")

    async def mensaje_inicial(self) -> Optional[dict[str, Any]]:
        """Notificación que abrió la app desde cerrada (`titulo`, `cuerpo`, `datos`), si hubo."""
        return await self._invoke_method("mensaje_inicial")
