import pytest

from parking_app.core.validadores import (
    normalizar_nombre,
    requisitos_password_faltantes,
    validar_correo_institucional,
    validar_nombre_apellido_persona,
    validar_password,
)


@pytest.mark.parametrize(
    "nombre",
    ["Ana Sofía", "Ñeco", "Müller", "María-José", "D'Angelo", "Ma. Guadalupe", "  de la Cruz  ", ""],
)
def test_nombre_valido(nombre):
    assert validar_nombre_apellido_persona(nombre) is None


@pytest.mark.parametrize("nombre", ["Ana2", "123", "P3rez", "Ana_Sofía", "Ana@", "José 2°"])
def test_nombre_con_numeros_o_simbolos(nombre):
    assert validar_nombre_apellido_persona(nombre) == "Solo se permiten letras, sin números ni símbolos"


def test_nombre_sin_letras():
    assert validar_nombre_apellido_persona("- .") == "Escribe al menos una letra"


def test_normalizar_nombre_quita_espacios_sobrantes():
    assert normalizar_nombre("  Ana    Sofía ") == "Ana Sofía"


@pytest.mark.parametrize(
    "correo",
    ["alumno@itsx.edu.mx", "  Alumno.Uno@XALAPA.TECNM.MX  ", "l20190001@xalapa.tecnm.mx"],
)
def test_correo_institucional_valido(correo):
    assert validar_correo_institucional(correo) is None


@pytest.mark.parametrize(
    "correo",
    ["", "alumno@gmail.com", "alumno@itsx.edu.mx.com", "alumno@sub.itsx.edu.mx", "sin-arroba"],
)
def test_correo_institucional_invalido(correo):
    assert validar_correo_institucional(correo) is not None


def test_password_valida():
    assert validar_password("Segura#2026") is None


def test_password_reporta_todos_los_faltantes():
    assert requisitos_password_faltantes("abc") == [
        "una mayúscula",
        "un número",
        "un carácter especial",
    ]
    assert validar_password("abc12345") == (
        "La contraseña debe incluir una mayúscula, un número y un carácter especial"
    )


def test_password_vacia():
    assert validar_password("") == "Ingresa una contraseña"
