"""Copia local de la reserva vigente para mostrar el QR sin internet (RNF-08).

Se guarda en el directorio de datos de la app (FLET_APP_STORAGE_DATA en el
teléfono). Es una caché: si falla, la reserva sigue existiendo en el servidor.
"""

import json
import logging
import os
from pathlib import Path

from parking_app.models.reserva_cajon import ReservaCajon

logger = logging.getLogger(__name__)

ARCHIVO = "reserva_activa.json"


def _directorio_predeterminado() -> Path:
    datos = os.environ.get("FLET_APP_STORAGE_DATA")
    return Path(datos) if datos else Path.home() / ".estacionamiento_itsx"


class AlmacenReserva:
    def __init__(self, directorio: Path | None = None) -> None:
        self._directorio = directorio or _directorio_predeterminado()

    @property
    def _ruta(self) -> Path:
        return self._directorio / ARCHIVO

    def guardar(self, id_usuario: str, reserva: ReservaCajon) -> None:
        try:
            self._directorio.mkdir(parents=True, exist_ok=True)
            self._ruta.write_text(
                json.dumps({"id_usuario": id_usuario, "reserva": reserva.to_dict()}),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("No se pudo guardar la reserva en el teléfono")

    def leer(self, id_usuario: str) -> ReservaCajon | None:
        """La reserva guardada de este estudiante (otra cuenta en el mismo teléfono no la ve)."""
        try:
            datos = json.loads(self._ruta.read_text(encoding="utf-8"))
            if datos.get("id_usuario") != id_usuario:
                return None
            return ReservaCajon.from_dict(datos["reserva"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("Reserva local ilegible; se ignora", exc_info=True)
            return None

    def borrar(self) -> None:
        try:
            self._ruta.unlink(missing_ok=True)
        except OSError:
            logger.exception("No se pudo borrar la reserva local")
