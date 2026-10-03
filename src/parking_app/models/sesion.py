import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class EstadoSesion(StrEnum):
    ACTIVO = "activo"
    INACTIVO = "inactivo"

# Clase para representar dentro del modelo a la sesion
@dataclass
class Sesion:
    """Fila de `public.sesiones` (historial propio, independiente de auth.sessions)."""

    id_usuario: str
    token: str = field(repr=False)
    fecha_acceso: datetime
    fecha_cierre_sesion: datetime | None = None
    estado: EstadoSesion = EstadoSesion.ACTIVO
    id_sesion: str = field(default_factory=lambda: str(uuid4()))

    @property
    def activa(self) -> bool:
        return self.estado == EstadoSesion.ACTIVO and self.fecha_cierre_sesion is None

    @property
    def huella_token(self) -> str:
        """SHA-256 del token: la tabla guarda la huella, nunca el JWT utilizable."""
        return hashlib.sha256(self.token.encode()).hexdigest()

    def to_row(self) -> dict[str, Any]:
        return {
            "id_sesion": self.id_sesion,
            "id_usuario": self.id_usuario,
            "token": self.huella_token,
            "fecha_acceso": self.fecha_acceso.isoformat(),
            "estado": self.estado.value,
        }
