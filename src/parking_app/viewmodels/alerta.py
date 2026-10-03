from dataclasses import dataclass


@dataclass(frozen=True)
class Alerta:
    """Mensaje de advertencia listo para mostrar en el banner de una pantalla."""

    titulo: str
    detalle: str | None = None


_MOTIVOS_PASSWORD_DEBIL = {
    "length": "es demasiado corta",
    "characters": "le faltan tipos de caracteres",
    "pwned": "apareció en una filtración de datos conocida",
}


def mensaje_password_debil(razones: list[str]) -> str:
    """Texto para el campo de contraseña cuando Supabase la rechaza por débil."""
    motivos = [_MOTIVOS_PASSWORD_DEBIL[r] for r in razones if r in _MOTIVOS_PASSWORD_DEBIL]
    if not motivos:
        return "Esta contraseña es demasiado débil; prueba con una más larga"
    return "Esta contraseña " + " y ".join(motivos) + "; elige otra"
