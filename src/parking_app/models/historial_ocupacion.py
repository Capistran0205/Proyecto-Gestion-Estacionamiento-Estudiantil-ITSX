"""Placeholder: el historial de horas está fuera del alcance de la Fase 1."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class HistorialOcupacion:
    id_historial: int
    id_usuario: str
    id_cajon: int
    fecha_entrada: datetime
    fecha_salida: datetime | None = None
