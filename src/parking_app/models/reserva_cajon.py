"""Placeholder: la reserva de cajón está fuera del alcance de la Fase 1."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ReservaCajon:
    id_reserva: int
    id_usuario: str
    id_cajon: int
    fecha_inicio: datetime
    fecha_fin: datetime | None = None
