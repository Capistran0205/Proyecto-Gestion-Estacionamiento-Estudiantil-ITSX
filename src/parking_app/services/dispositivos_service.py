"""Tokens FCM del dispositivo en `dispositivos_fcm` (Fase 2, notificaciones push).

El backend envía los avisos a los tokens de esta tabla. El alta pasa por la rpc
`registrar_token_fcm` (si el token ya era de otra cuenta en el mismo teléfono, pasa
al usuario actual) y la baja es un DELETE que la política `delete_propio` permite.
Ambas llevan el JWT de la sesión. Son bloqueantes (red): usar desde un hilo.
"""

import logging
from collections.abc import Callable
from typing import Any

import httpx

from parking_app.services.reservas_service import ReservaError, ReservasNoDisponiblesError

logger = logging.getLogger(__name__)


class DispositivosService:
    def __init__(
        self,
        token_factory: Callable[[], str | None],
        url_factory: Callable[[], tuple[str, str]] | None = None,
        transporte: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        if url_factory is None:
            from parking_app.core.config import get_settings

            def url_factory() -> tuple[str, str]:
                s = get_settings()
                return s.supabase_url, s.supabase_anon_key

        self._token_factory = token_factory
        self._url_factory = url_factory
        self._transporte = transporte
        self._timeout = timeout

    def registrar_token(self, token: str, plataforma: str = "android") -> None:
        self._peticion(
            "POST", "/rest/v1/rpc/registrar_token_fcm", "registrar_token_fcm",
            json={"p_token": token, "p_plataforma": plataforma},
        )

    def borrar_token(self, token: str) -> None:
        self._peticion(
            "DELETE", "/rest/v1/dispositivos_fcm", "dispositivos_fcm",
            params={"token": f"eq.{token}"},
        )

    def _peticion(self, metodo: str, ruta: str, nombre: str, **opciones: Any) -> None:
        jwt = self._token_factory()
        if not jwt:
            raise ReservaError("NO_AUTENTICADO", "Tu sesión expiró. Inicia sesión de nuevo.", 401)
        url, anon = self._url_factory()
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transporte) as cliente:
                r = cliente.request(
                    metodo,
                    f"{url.rstrip('/')}{ruta}",
                    headers={"Authorization": f"Bearer {jwt}", "apikey": anon},
                    **opciones,
                )
        except httpx.HTTPError as e:
            raise ReservasNoDisponiblesError(f"{nombre}: {e}", sin_red=True) from e
        if r.is_success:
            return
        if r.status_code == 401:
            raise ReservaError("NO_AUTENTICADO", "Tu sesión expiró. Inicia sesión de nuevo.", 401)
        logger.warning("%s respondió HTTP %s: %s", nombre, r.status_code, r.text[:200])
        raise ReservasNoDisponiblesError(f"{nombre}: HTTP {r.status_code}")
