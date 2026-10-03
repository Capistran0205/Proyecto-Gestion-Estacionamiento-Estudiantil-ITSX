from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class MedioTransporte(StrEnum):
    MOTOCICLETA = "motocicleta"
    VEHICULO = "vehiculo"


class EstadoCuenta(StrEnum):
    ACTIVO = "activo"
    INACTIVO = "inactivo"


class Rol(StrEnum):
    ESTUDIANTE = "estudiante"
    ADMINISTRADOR = "administrador"

# Clase para representar dentro del modelo al usuario
@dataclass
class Usuario:
    """Fila de `public.usuarios` (id_usuario = auth.users.id)."""

    id_usuario: str
    nombre: str
    apellido_paterno: str
    apellido_materno: str | None
    correo_institucional: str
    medio_transporte: MedioTransporte | None
    rol: Rol = Rol.ESTUDIANTE
    fecha_registro: datetime | None = None
    tiempo_bloqueo_acceso: datetime | None = None
    intentos_fallidos: int = 0
    estado_cuenta: EstadoCuenta = EstadoCuenta.ACTIVO
    # La contraseña vive solo en Supabase Auth; nunca se guarda en la tabla.
    contraseña: str | None = field(default=None, repr=False)

    @property
    def nombre_completo(self) -> str:
        return " ".join(
            p for p in (self.nombre, self.apellido_paterno, self.apellido_materno) if p
        )

    @property
    def activo(self) -> bool:
        return self.estado_cuenta == EstadoCuenta.ACTIVO

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Usuario":
        medio = row.get("medio_transporte")
        return cls(
            id_usuario=row["id_usuario"],
            nombre=row.get("nombre") or "",
            apellido_paterno=row.get("apellido_paterno") or "",
            apellido_materno=row.get("apellido_materno"),
            correo_institucional=row["correo_institucional"],
            medio_transporte=MedioTransporte(medio) if medio else None,
            rol=Rol(row.get("rol") or Rol.ESTUDIANTE),
            fecha_registro=_parse_fecha(row.get("fecha_registro")),
            tiempo_bloqueo_acceso=_parse_fecha(row.get("tiempo_bloqueo_acceso")),
            intentos_fallidos=row.get("intentos_fallidos") or 0,
            estado_cuenta=EstadoCuenta(row.get("estado_cuenta") or EstadoCuenta.ACTIVO),
        )

    def to_row(self) -> dict[str, Any]:
        """Fila para insertar en `usuarios` (sin contraseña).

        rol, estado_cuenta, fecha_registro e intentos_fallidos se dejan a los
        defaults de la base de datos.
        """
        return {
            "id_usuario": self.id_usuario,
            "nombre": self.nombre,
            "apellido_paterno": self.apellido_paterno,
            "apellido_materno": self.apellido_materno or None,
            "correo_institucional": self.correo_institucional,
            "medio_transporte": self.medio_transporte.value if self.medio_transporte else None,
        }


def _parse_fecha(valor: Any) -> datetime | None:
    if valor is None or isinstance(valor, datetime):
        return valor
    return datetime.fromisoformat(str(valor))
