"""La vista de recuperación refleja cada paso de los mockups (sin página real)."""

import asyncio
from unittest.mock import MagicMock

from parking_app.core import theme
from parking_app.services.auth_service import CodigoInvalidoError
from parking_app.viewmodels.recuperar_password_viewmodel import RecuperarPasswordViewModel
from parking_app.views.recuperar_password_view import RecuperarPasswordView


def _vista():
    auth = MagicMock()
    vm = RecuperarPasswordViewModel(auth, MagicMock(), MagicMock())
    vista = RecuperarPasswordView(vm)
    vista.montar()
    return vista, vm, auth


def _ir_al_paso_2(vm):
    async def avanzar():
        vm.set_correo("ana@itsx.edu.mx")
        await vm.enviar_codigo()
        vm.liberar()  # detiene el temporizador fuera del loop de prueba

    asyncio.run(avanzar())


def test_paso_1():
    vista, _, _ = _vista()

    assert vista._indicador.texto == "Paso 1 de 3"
    assert vista._paso_correo.visible and not vista._paso_codigo.visible
    assert vista._boton.content == "Enviar código"
    assert not vista._fila_codigo_nuevo.visible


def test_paso_2_muestra_correo_y_vencimiento():
    vista, vm, _ = _vista()
    _ir_al_paso_2(vm)

    assert vista._indicador.texto == "Paso 2 de 3"
    assert vista._paso_codigo.visible
    assert vista._correo_destino.text == "ana@itsx.edu.mx"
    assert vista._tiempo.text == "10:00"
    assert vista._fila_vencimiento.visible and vista._reenviar.visible
    assert not vista._banner_codigo.control.visible
    assert vista._boton.content == "Verificar código"


def test_paso_2_codigo_invalido_como_el_mockup():
    vista, vm, auth = _vista()
    _ir_al_paso_2(vm)
    auth.verificar_codigo_recuperacion.side_effect = CodigoInvalidoError("x")
    vm.set_codigo("000000")

    asyncio.run(vm.verificar_codigo())

    assert vista._banner_codigo.control.visible
    assert vista._banner_codigo.titulo == "El código no es válido o ya venció"
    assert vista._codigo.campo.border_color == theme.NARANJA
    assert vista._codigo.campo.suffix_icon is not None
    assert not vista._fila_vencimiento.visible
    assert not vista._reenviar.visible
    assert vista._fila_codigo_nuevo.visible


def test_paso_3_y_exito():
    vista, vm, _ = _vista()
    _ir_al_paso_2(vm)
    vm.set_codigo("123456")
    asyncio.run(vm.verificar_codigo())

    assert vista._indicador.texto == "Paso 3 de 3"
    assert vista._boton.content == "Guardar contraseña"

    vm.set_password("Nueva#2026")
    vm.set_confirmar_password("Nueva#2026")
    asyncio.run(vm.guardar_password())

    assert vista._pantalla_exito.control.visible
    assert not vista._flujo.visible
