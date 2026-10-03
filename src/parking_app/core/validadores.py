"""Validadores compartidos por Login, Registro y Recuperar contraseña.

Cada función devuelve el mensaje de error listo para mostrar, o None si es válido.
"""

import re

from parking_app.core.config import DOMINIOS_CORREO_PERMITIDOS

_PATRON_CORREO = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})$")

# Letras latinas con acentos, ñ y ü (À-ÿ sin × ni ÷). Es el mismo conjunto que
# usa el CHECK de `usuarios` en Supabase.
_LETRAS_NOMBRE = "A-Za-zÀ-ÖØ-öø-ÿ"
# Un carácter válido en nombres y apellidos: letra, espacio, apóstrofo, punto
# ("Ma. Guadalupe") o guion. Lo reutiliza el filtro de escritura de la View.
PATRON_CARACTER_NOMBRE = rf"[{_LETRAS_NOMBRE} '’.\-]"
_PATRON_NOMBRE = re.compile(rf"^{PATRON_CARACTER_NOMBRE}+$")
_PATRON_LETRA = re.compile(rf"[{_LETRAS_NOMBRE}]")

_REQUISITOS_PASSWORD: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("longitud", re.compile(r".{8,}"), "al menos 8 carácteres"),
    ("mayuscula", re.compile(r"[A-ZÁÉÍÓÚÑÜ]"), "una mayúscula"),
    ("minuscula", re.compile(r"[a-záéíóúñü]"), "una minúscula"),
    ("numero", re.compile(r"\d"), "un número"),
    ("especial", re.compile(r"[^A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü\s]"), "un carácter especial"),
)


def normalizar_correo(correo: str) -> str:
    return correo.strip().lower()


def validar_correo_institucional(correo: str) -> str | None:
    correo = normalizar_correo(correo)
    if not correo:
        return "Ingresa tu correo institucional"
    coincidencia = _PATRON_CORREO.match(correo)
    if not coincidencia:
        return "Correo no válido"
    if coincidencia.group(1) not in DOMINIOS_CORREO_PERMITIDOS:
        dominios = " o ".join(f"@{d}" for d in DOMINIOS_CORREO_PERMITIDOS)
        return f"Usa tu correo institucional ({dominios})"
    return None


def estado_requisitos_password(password: str) -> dict[str, bool]:
    """Clave del requisito ("mayuscula", "minuscula", "numero", "especial") -> ¿se cumple?"""
    return {clave: bool(patron.search(password)) for clave, patron, _ in _REQUISITOS_PASSWORD}


def requisitos_password_faltantes(password: str) -> list[str]:
    return [desc for _, patron, desc in _REQUISITOS_PASSWORD if not patron.search(password)]


def validar_password(password: str) -> str | None:
    if not password:
        return "Ingresa una contraseña"
    faltantes = requisitos_password_faltantes(password)
    if faltantes:
        return "La contraseña debe incluir " + _unir(faltantes)
    return None


def normalizar_nombre(valor: str) -> str:
    """Quita espacios sobrantes: "  ana   sofía " -> "ana sofía"."""
    return " ".join(valor.split())

# Función para validar nombre y apellidos enviados desde el view
def validar_nombre_apellido_persona(valor: str) -> str | None:
    """Nombre o apellido: solo letras, espacios, apóstrofo, punto y guion.

    Un valor vacío es válido aquí; si el campo es obligatorio se valida aparte.
    """
    valor = normalizar_nombre(valor)
    if not valor:
        return None
    if not _PATRON_NOMBRE.match(valor):
        return "Solo se permiten letras, sin números ni símbolos"
    if not _PATRON_LETRA.search(valor):
        return "Escribe al menos una letra"
    return None


def validar_requerido(valor: str, nombre_campo: str) -> str | None:
    return None if valor.strip() else f"Ingresa {nombre_campo}"


def _unir(partes: list[str]) -> str:
    if len(partes) == 1:
        return partes[0]
    return ", ".join(partes[:-1]) + " y " + partes[-1]
