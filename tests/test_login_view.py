"""La vista se construye y refleja el estado del ViewModel (sin página real)."""

import asyncio
from unittest.mock import MagicMock

from parking_app.core import theme
from parking_app.services.auth_service import CredencialesInvalidasError
from parking_app.viewmodels.login_viewmodel import LoginViewModel
from parking_app.views.login_view import LoginView


def _vista():
    auth = MagicMock()
    vm = LoginViewModel(auth, MagicMock(), MagicMock(), MagicMock())
    vista = LoginView(vm)
    vista.montar()
    return vista, vm, auth


def test_estado_inicial_como_el_mockup():
    vista, _, _ = _vista()

    assert vista.view.route == "/login"
    assert not vista._banner.control.visible
    assert vista._correo.texto_ayuda.value == "Usa tu correo @itsx.edu.mx o @xalapa.tecnm.mx"
    assert vista._correo.campo.border_color == theme.BORDE_CAMPO
    assert vista._password.campo.password
    assert not vista._boton.disabled


def test_credenciales_invalidas_muestran_banner_y_bordes_naranja():
    vista, vm, auth = _vista()
    auth.iniciar_sesion.side_effect = CredencialesInvalidasError(2)
    vm.set_correo("alumno@itsx.edu.mx")
    vm.set_password("mala")

    asyncio.run(vm.iniciar_sesion())

    assert vista._banner.control.visible
    assert vista._banner._titulo.value == "Correo o contraseña incorrectos"
    assert vista._correo.campo.border_color == theme.NARANJA
    assert vista._password.campo.border_color == theme.NARANJA
    assert vista._password.campo.value == "mala"


def test_error_de_validacion_reemplaza_texto_de_ayuda():
    vista, vm, _ = _vista()
    vm.set_correo("alumno@gmail.com")

    asyncio.run(vm.iniciar_sesion())

    assert "institucional" in vista._correo.error.texto
    assert not vista._correo.texto_ayuda.visible
    assert vista._correo.campo.border_color == theme.NARANJA


def test_desmontar_deja_de_escuchar():
    vista, vm, _ = _vista()
    vista.desmontar()
    vm.set_correo("x")  # No debe fallar ni repintar
    assert vista._correo.campo.value == ""
