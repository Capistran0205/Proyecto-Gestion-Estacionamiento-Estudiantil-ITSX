"""La vista de registro refleja los estados de los mockups (sin página real)."""

import asyncio
import re
from unittest.mock import MagicMock

import pytest

from parking_app.core import theme
from parking_app.models.usuario import MedioTransporte, Usuario
from parking_app.services.auth_service import (
    CorreoYaRegistradoError,
    DatosInvalidosError,
    ResultadoRegistro,
)
from parking_app.viewmodels.registro_viewmodel import RegistroViewModel
from parking_app.views.registro_view import RegistroView


def _vista():
    auth = MagicMock()
    vm = RegistroViewModel(auth, MagicMock(), MagicMock(), MagicMock())
    vista = RegistroView(vm)
    vista.montar()
    return vista, vm, auth


def _llenar(vm):
    vm.set_nombre("Ana")
    vm.set_apellido_paterno("Pérez")
    vm.set_medio_transporte(MedioTransporte.MOTOCICLETA)
    vm.set_correo("ana@itsx.edu.mx")
    vm.set_password("Segura#2026")
    vm.set_confirmar_password("Segura#2026")


def test_estado_inicial():
    vista, _, _ = _vista()

    assert vista.view.route == "/registro"
    assert vista._banner.titulo is None
    assert not any(t.seleccionada for t in vista._opciones_transporte.values())
    assert vista._formulario.visible and not vista._exito.visible


def test_campos_faltantes_marcan_errores():
    vista, vm, _ = _vista()
    vm.set_nombre("Ana")

    asyncio.run(vm.crear_cuenta())

    assert vista._banner.titulo == "Faltan 5 campos por completar"
    assert vista._apellido_paterno.error.texto == "Campo obligatorio"
    assert vista._apellido_paterno.campo.border_color == theme.NARANJA
    assert vista._nombre.error.texto is None
    assert vista._apellido_materno.error.texto is None
    assert vista._error_transporte.texto == "Selecciona tu medio de transporte"
    tarjeta = vista._opciones_transporte[MedioTransporte.VEHICULO]
    assert tarjeta.control.border.top.color == theme.NARANJA


@pytest.mark.parametrize(
    ("texto", "aceptado"),
    [
        ("", True),  # se puede borrar hasta dejar el campo vacío
        ("A", True),
        ("Ma. Guadalupe D'Angelo-Núñez", True),
        ("A1", False),  # un número después de la primera letra
        ("1", False),
        ("Ana@", False),
    ],
)
def test_filtro_de_nombre_evalua_el_texto_completo(texto, aceptado):
    # Flet aplica el filtro con RegExp.hasMatch sobre el texto completo;
    # re.search tiene la misma semántica.
    vista, _, _ = _vista()
    for campo in (vista._nombre, vista._apellido_paterno, vista._apellido_materno):
        patron = campo.campo.input_filter.regex_string
        assert bool(re.search(patron, texto)) is aceptado


def test_campos_de_nombre_filtran_numeros_y_muestran_error():
    vista, vm, _ = _vista()
    assert vista._correo.campo.input_filter is None

    _llenar(vm)
    vm.set_apellido_materno("López2")  # p. ej. pegado desde otra app
    asyncio.run(vm.crear_cuenta())

    assert vista._apellido_materno.error.texto == (
        "Solo se permiten letras, sin números ni símbolos"
    )
    assert vista._apellido_materno.campo.border_color == theme.NARANJA


def test_seleccion_de_transporte_y_requisitos():
    vista, vm, _ = _vista()

    vm.set_medio_transporte(MedioTransporte.VEHICULO)
    vm.set_password("Segura#2026")

    assert vista._opciones_transporte[MedioTransporte.VEHICULO].seleccionada
    assert not vista._opciones_transporte[MedioTransporte.MOTOCICLETA].seleccionada
    iconos = [icono.color for icono, _ in vista._requisitos._filas]
    assert iconos == [theme.VERDE_AZULADO] * 5


def test_correo_duplicado_muestra_banner_con_acciones():
    vista, vm, auth = _vista()
    auth.registrar.side_effect = CorreoYaRegistradoError("dup")
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    assert vista._banner_duplicado.titulo == "Este correo ya está registrado"
    assert vista._correo.campo.border_color == theme.NARANJA
    assert vista._banner.titulo is None


def test_correo_rechazado_por_supabase_se_marca_en_el_campo():
    vista, vm, auth = _vista()
    auth.registrar.side_effect = DatosInvalidosError("No es posible enviar correos", "correo")
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    assert vista._correo.error.texto == "No es posible enviar correos"
    assert vista._correo.campo.border_color == theme.NARANJA
    assert vista._banner.titulo == "Revisa los campos marcados"


def test_pantalla_de_exito():
    vista, vm, auth = _vista()
    usuario = Usuario("uid", "Ana", "Pérez", None, "ana@itsx.edu.mx", MedioTransporte.MOTOCICLETA)
    auth.registrar.return_value = ResultadoRegistro(usuario, requiere_confirmacion=True)
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    assert vista._exito.visible and not vista._formulario.visible
    assert "ana@itsx.edu.mx" in vista._detalle_exito.value
