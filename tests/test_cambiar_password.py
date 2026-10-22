"""Módulo A: Cambiar contraseña (ViewModel + View)."""

import asyncio
from unittest.mock import MagicMock

from parking_app.services.auth_service import (
    CambioPasswordRevertidoError,
    CuentaBloqueadaError,
    PasswordActualIncorrectaError,
    PasswordRepetidaError,
)
from parking_app.viewmodels.cambiar_password_viewmodel import CambiarPasswordViewModel
from parking_app.views.cambiar_password_view import CambiarPasswordView

CORREO = "237o00526@itsx.edu.mx"


def _vm():
    auth, emqx, al_cambiar = MagicMock(), MagicMock(), MagicMock()
    auth.usuario_actual.correo_institucional = CORREO
    vm = CambiarPasswordViewModel(auth, emqx, MagicMock(), al_cambiar=al_cambiar)
    return vm, auth, emqx, al_cambiar


def _llenar(vm, actual="Actual#2026", nueva="Nueva#2026", confirmar=None):
    vm.set_actual(actual)
    vm.set_nueva(nueva)
    vm.set_confirmar(nueva if confirmar is None else confirmar)


def test_cambio_exitoso_usa_emqx_y_limpia_las_contraseñas():
    vm, auth, emqx, al_cambiar = _vm()
    _llenar(vm)

    asyncio.run(vm.actualizar())

    auth.cambiar_password.assert_called_once_with("Actual#2026", "Nueva#2026", emqx.crear_credencial)
    assert vm.completado
    assert (vm.actual, vm.nueva, vm.confirmar) == ("", "", "")
    al_cambiar.assert_called_once()


def test_validaciones_locales():
    vm, auth, _, _ = _vm()
    _llenar(vm, actual="", nueva="corta", confirmar="otra")
    asyncio.run(vm.actualizar())
    auth.cambiar_password.assert_not_called()
    assert vm.error_actual == "Escribe tu contraseña actual"
    assert vm.error_nueva == "Tu contraseña no cumple los requisitos"
    assert vm.error_confirmar == "Las contraseñas no coinciden"

    _llenar(vm, actual="Igual#2026", nueva="Igual#2026")
    asyncio.run(vm.actualizar())
    assert vm.error_nueva == "La nueva contraseña debe ser distinta a la actual"
    auth.cambiar_password.assert_not_called()


def test_requisitos_en_vivo():
    vm, _, _, _ = _vm()
    vm.set_nueva("abcdefgh")
    cumplidos = dict(vm.requisitos_password)
    assert cumplidos["Al menos 8 caracteres"] and cumplidos["Al menos una letra minúscula"]
    assert not cumplidos["Al menos un número"]


def test_contraseña_actual_incorrecta_como_el_mockup():
    vm, auth, _, al_cambiar = _vm()
    auth.cambiar_password.side_effect = PasswordActualIncorrectaError(2)
    _llenar(vm)

    asyncio.run(vm.actualizar())

    assert vm.error_actual == "La contraseña actual no es correcta"
    assert vm.alerta.titulo == "No se pudo cambiar la contraseña"
    assert vm.alerta.detalle == "La contraseña actual no es correcta. Inténtalo de nuevo."
    assert not vm.completado
    al_cambiar.assert_not_called()

    # Al corregirla desaparecen el aviso y el error.
    vm.set_actual("Actual#2027")
    assert vm.error_actual is None and vm.alerta is None


def test_bloqueo_por_intentos():
    vm, auth, _, _ = _vm()
    auth.cambiar_password.side_effect = CuentaBloqueadaError(170)
    _llenar(vm)
    asyncio.run(vm.actualizar())
    assert vm.alerta.titulo == "Demasiados intentos"
    assert "3 minutos" in vm.alerta.detalle


def test_contraseña_repetida_en_supabase():
    vm, auth, _, _ = _vm()
    auth.cambiar_password.side_effect = PasswordRepetidaError("x")
    _llenar(vm)
    asyncio.run(vm.actualizar())
    assert vm.error_nueva == "Elige una contraseña distinta a la actual"


def test_falla_de_emqx_revertida_informa_que_no_cambio():
    vm, auth, _, al_cambiar = _vm()
    auth.cambiar_password.side_effect = CambioPasswordRevertidoError("x")
    _llenar(vm)
    asyncio.run(vm.actualizar())
    assert "tu contraseña no cambió" in vm.alerta.detalle
    assert not vm.completado
    al_cambiar.assert_not_called()


# --- View ---

def test_vista_formulario_y_exito():
    vm, auth, _, _ = _vm()
    vista = CambiarPasswordView(vm)
    vista.montar()
    assert vista.view.route == "/perfil/password"
    assert vista._formulario.visible and not vista._exito.visible

    auth.cambiar_password.side_effect = PasswordActualIncorrectaError(2)
    _llenar(vm)
    asyncio.run(vm.actualizar())
    assert vista._banner.titulo == "No se pudo cambiar la contraseña"
    assert vista._actual.error.texto == "La contraseña actual no es correcta"

    auth.cambiar_password.side_effect = None
    vm.set_actual("Actual#2026")
    asyncio.run(vm.actualizar())
    assert vista._exito.visible and not vista._formulario.visible
    detalle = "".join(s.text for s in vista._pantalla_exito.detalle.spans)
    assert detalle == f"Enviamos un aviso a {CORREO} como medida de seguridad."
