"""Reserva de cajón a través de las Edge Functions (Fase 2, Módulo B).

La app ya no escribe en `reservas`: cada cambio lo hace el backend con la rpc
correspondiente. Las llamadas llevan el JWT de la sesión; el backend toma de
ahí el id del estudiante. Son bloqueantes (red): usar desde un hilo.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from parking_app.models.reserva_cajon import (
    BloqueoCajon,
    LlegadaRegistrada,
    ReglasReserva,
    ReservaCajon,
)

logger = logging.getLogger(__name__)

# Con la etiqueta del cajón embebida (cajones es legible para authenticated).
COLUMNAS_RESERVA = (
    "id_reserva,id_cajon,codigo_qr,estado,fecha_inicio,fecha_fin,cronometro,fecha_llegada,"
    "fecha_usuario,notificado_fin_proximo,cajones(etiqueta)"
)
# Administrador: sin codigo_qr (no lo necesita para la lista ni para el motivo).
COLUMNAS_ADMIN = COLUMNAS_RESERVA.replace("codigo_qr,", "")


class ReservaError(Exception):
    """Regla de negocio rechazada por el backend (código de la función SQL).

    El mensaje viene redactado para el estudiante.
    """

    def __init__(self, codigo: str, mensaje: str, status: int | None = None) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.status = status


class ReservasNoDisponiblesError(Exception):
    """Falla de red o del servidor (no es una regla de negocio).

    `sin_red` distingue "no hubo respuesta" de "el servidor respondió con error"
    (p. ej. 404 si la función no está desplegada): la app muestra avisos distintos.
    """

    def __init__(self, mensaje: str, sin_red: bool = False) -> None:
        super().__init__(mensaje)
        self.sin_red = sin_red


class ReservasService:
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

    def bloquear_cajon(self, id_cajon: int) -> BloqueoCajon:
        datos = self._invocar("bloquear-cajon", {"id_cajon": id_cajon})
        try:
            return BloqueoCajon.from_dict(datos)
        except (KeyError, TypeError, ValueError) as e:
            raise ReservasNoDisponiblesError(f"Respuesta inesperada de bloquear-cajon: {e}") from e

    def liberar_bloqueo(self, id_cajon: int | None = None) -> None:
        self._invocar("liberar-bloqueo", {"id_cajon": id_cajon})

    def crear_reserva(self, id_cajon: int, inicio: datetime, fin: datetime) -> ReservaCajon:
        datos = self._invocar(
            "crear-reserva",
            {"id_cajon": id_cajon, "fecha_inicio": inicio.isoformat(), "fecha_fin": fin.isoformat()},
        )
        try:
            return ReservaCajon.from_dict(datos)
        except (KeyError, TypeError, ValueError) as e:
            raise ReservasNoDisponiblesError(f"Respuesta inesperada de crear-reserva: {e}") from e

    def cancelar_reserva(self, id_reserva: str) -> None:
        self._invocar("cancelar-reserva", {"id_reserva": id_reserva})

    def extender_reserva(self, id_reserva: str) -> datetime:
        """+1 h (RF-12). Devuelve la nueva hora de fin."""
        datos = self._invocar("extender-reserva", {"id_reserva": id_reserva})
        try:
            return datetime.fromisoformat(str(datos["fecha_fin"]))
        except (KeyError, ValueError) as e:
            raise ReservasNoDisponiblesError(f"Respuesta inesperada de extender-reserva: {e}") from e

    def confirmar_salida(self, id_reserva: str) -> None:
        self._invocar("confirmar-salida", {"id_reserva": id_reserva})

    def reglas(self) -> ReglasReserva:
        """Minutos para llegar y de tolerancia (config_sistema, vía reglas-reserva)."""
        return ReglasReserva.from_dict(self._invocar("reglas-reserva", {}))

    # --- Administrador (Módulo C) ---

    def confirmar_llegada(self, codigo_qr: str) -> LlegadaRegistrada:
        """Valida el QR y registra la llegada (RF-10/RF-11). El rol lo valida el backend."""
        datos = self._invocar("confirmar-llegada", {"codigo_qr": codigo_qr})
        try:
            return LlegadaRegistrada.from_dict(datos)
        except (KeyError, TypeError, ValueError) as e:
            raise ReservasNoDisponiblesError(f"Respuesta inesperada de confirmar-llegada: {e}") from e

    def reservas_activas(self) -> list[ReservaCajon]:
        """Pendientes de llegada y en uso, en el orden en que se crearon (RLS: solo administrador)."""
        filas = self._peticion(
            "GET", "/rest/v1/reservas", "reservas",
            params={
                "select": COLUMNAS_ADMIN,
                "estado": "in.(pendiente_llegada,en_uso)",
                "order": "fecha_usuario.asc",
            },
        )
        if not isinstance(filas, list):
            raise ReservasNoDisponiblesError("Respuesta inesperada al consultar reservas")
        try:
            return [ReservaCajon.from_dict(f) for f in filas]
        except (KeyError, TypeError, ValueError) as e:
            raise ReservasNoDisponiblesError(f"Reserva con formato inesperado: {e}") from e

    def reserva_por_codigo(self, codigo_qr: str) -> ReservaCajon | None:
        """Datos de un código rechazado (cajón, horas) para mostrar el motivo."""
        return self._consultar({"codigo_qr": f"eq.{codigo_qr}"}, COLUMNAS_ADMIN)

    # --- Lectura (RLS: el estudiante solo ve sus reservas) ---

    def obtener_reserva(self, id_reserva: str) -> ReservaCajon | None:
        """La reserva en su estado actual (también si ya terminó)."""
        return self._consultar({"id_reserva": f"eq.{id_reserva}"})

    def reserva_vigente(self, id_usuario: str) -> ReservaCajon | None:
        return self._consultar({
            "id_usuario_estudiante": f"eq.{id_usuario}",
            "estado": "in.(pendiente_llegada,en_uso)",
        })

    def _consultar(
        self, filtros: dict[str, str], columnas: str = COLUMNAS_RESERVA
    ) -> ReservaCajon | None:
        filas = self._peticion(
            "GET", "/rest/v1/reservas", "reservas",
            params={"select": columnas, "limit": "1", **filtros},
        )
        if not isinstance(filas, list):
            raise ReservasNoDisponiblesError("Respuesta inesperada al consultar reservas")
        if not filas:
            return None
        try:
            return ReservaCajon.from_dict(filas[0])
        except (KeyError, TypeError, ValueError) as e:
            raise ReservasNoDisponiblesError(f"Reserva con formato inesperado: {e}") from e

    def _invocar(self, funcion: str, cuerpo: dict[str, Any]) -> dict[str, Any]:
        datos = self._peticion("POST", f"/functions/v1/{funcion}", funcion, json=cuerpo)
        if not isinstance(datos, dict):
            raise ReservasNoDisponiblesError(f"{funcion}: respuesta inesperada")
        return datos

    def _peticion(self, metodo: str, ruta: str, nombre: str, **opciones: Any) -> Any:
        token = self._token_factory()
        if not token:
            raise ReservaError("NO_AUTENTICADO", "Tu sesión expiró. Inicia sesión de nuevo.", 401)
        url, anon = self._url_factory()
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transporte) as cliente:
                r = cliente.request(
                    metodo,
                    f"{url.rstrip('/')}{ruta}",
                    headers={"Authorization": f"Bearer {token}", "apikey": anon},
                    **opciones,
                )
        except httpx.HTTPError as e:
            raise ReservasNoDisponiblesError(f"{nombre}: {e}", sin_red=True) from e

        try:
            datos = r.json()
        except ValueError:
            datos = None
        if r.is_success and datos is not None:
            return datos

        error = datos.get("error") if isinstance(datos, dict) else None
        if isinstance(error, dict) and error.get("codigo") and error["codigo"] != "ERROR_INTERNO":
            raise ReservaError(str(error["codigo"]), str(error.get("mensaje") or ""), r.status_code)
        if r.status_code == 401:
            # El gateway rechazó el JWT (sin cuerpo con código).
            raise ReservaError("NO_AUTENTICADO", "Tu sesión expiró. Inicia sesión de nuevo.", 401)
        logger.warning("%s respondió HTTP %s: %s", nombre, r.status_code, r.text[:200])
        raise ReservasNoDisponiblesError(f"{nombre}: HTTP {r.status_code}")
