import asyncio
from unittest.mock import MagicMock

import pytest

from parking_app.services.auth_service import (
    CodigoInvalidoError,
    LimiteCorreosError,
    PasswordDebilError,
    PasswordRepetidaError,
    ServicioNoDisponibleError,
    SinSesionError,
)
from parking_app.viewmodels.recuperar_password_viewmodel import Paso, RecuperarPasswordViewModel

CORREO = "ana@itsx.edu.mx"
NUEVA = "Nueva#2026"


class Reloj:
    def __init__(self) -> None:
        self.ahora = 0.0

    def __call__(self) -> float:
        return self.ahora


def _vm():
    auth, emqx, login, reloj = MagicMock(), MagicMock(), MagicMock(), Reloj()
    vm = RecuperarPasswordViewModel(auth, emqx, login, reloj=reloj)
    return vm, auth, emqx, login, reloj


def _en_paso(vm, paso):
    """Avanza el flujo hasta `paso` dentro de un event loop (el temporizador lo necesita)."""

    async def avanzar():
        vm.set_correo(" Ana@ITSX.edu.mx ")
        await vm.enviar_codigo()
        if paso >= Paso.NUEVA_PASSWORD:
            vm.set_codigo("123456")
            await vm.verificar_codigo()

    asyncio.run(avanzar())


def test_paso_1_valida_correo_institucional():
    vm, auth, _, _, _ = _vm()
    vm.set_correo("ana@gmail.com")

    asyncio.run(vm.enviar_codigo())

    assert vm.paso == Paso.CORREO
    assert "institucional" in vm.error_correo
    auth.solicitar_restablecimiento.assert_not_called()


def test_paso_1_envia_codigo_y_avanza_con_temporizador():
    vm, auth, _, _, reloj = _vm()
    _en_paso(vm, Paso.CODIGO)

    auth.solicitar_restablecimiento.assert_called_once_with(CORREO)
    assert vm.paso == Paso.CODIGO
    assert vm.numero_paso == 2
    assert vm.texto_vencimiento == "10:00"
    reloj.ahora += 61
    assert vm.texto_vencimiento == "08:59"
    assert not vm.mostrar_error_codigo


def test_limite_de_correos():
    vm, auth, _, _, _ = _vm()
    auth.solicitar_restablecimiento.side_effect = LimiteCorreosError("x")
    vm.set_correo(CORREO)

    asyncio.run(vm.enviar_codigo())

    assert vm.paso == Paso.CORREO
    assert vm.alerta.titulo == "Espera un momento"


def test_codigo_solo_acepta_digitos():
    vm, _, _, _, _ = _vm()
    vm.set_codigo("12a 3-4")
    assert vm.codigo == "1234"


def test_codigo_vacio():
    vm, auth, _, _, _ = _vm()
    _en_paso(vm, Paso.CODIGO)

    asyncio.run(vm.verificar_codigo())

    assert vm.error_codigo == "Escribe el código de verificación"
    auth.verificar_codigo_recuperacion.assert_not_called()


def test_codigo_invalido_muestra_estado_de_error_y_se_limpia_al_escribir():
    vm, auth, _, _, _ = _vm()
    _en_paso(vm, Paso.CODIGO)
    auth.verificar_codigo_recuperacion.side_effect = CodigoInvalidoError("x")
    vm.set_codigo("000000")

    asyncio.run(vm.verificar_codigo())

    assert vm.paso == Paso.CODIGO
    assert vm.mostrar_error_codigo
    vm.set_codigo("1")
    assert not vm.mostrar_error_codigo


def test_codigo_vencido_por_tiempo():
    vm, _, _, _, reloj = _vm()
    _en_paso(vm, Paso.CODIGO)

    reloj.ahora += 600

    assert vm.codigo_vencido
    assert vm.mostrar_error_codigo
    assert vm.texto_vencimiento == "00:00"


def test_reenviar_reinicia_temporizador_y_limpia_error():
    vm, auth, _, _, reloj = _vm()
    _en_paso(vm, Paso.CODIGO)
    reloj.ahora += 600
    vm.codigo = "111111"

    asyncio.run(vm.reenviar_codigo())

    assert auth.solicitar_restablecimiento.call_count == 2
    assert not vm.mostrar_error_codigo
    assert vm.codigo == ""
    assert vm.texto_vencimiento == "10:00"


def test_codigo_correcto_avanza_al_paso_3():
    vm, auth, _, _, _ = _vm()
    _en_paso(vm, Paso.NUEVA_PASSWORD)

    auth.verificar_codigo_recuperacion.assert_called_once_with(CORREO, "123456")
    assert vm.paso == Paso.NUEVA_PASSWORD
    assert vm.numero_paso == 3


def test_paso_3_valida_requisitos_y_coincidencia():
    vm, auth, _, _, _ = _vm()
    _en_paso(vm, Paso.NUEVA_PASSWORD)
    vm.set_password("debil")
    vm.set_confirmar_password("otra")

    asyncio.run(vm.guardar_password())

    assert vm.error_password == "Tu contraseña no cumple los requisitos"
    assert vm.error_confirmar == "Las contraseñas no coinciden"
    auth.confirmar_nueva_password.assert_not_called()
    vm.set_password(NUEVA)
    vm.set_confirmar_password(NUEVA)
    assert vm.error_password is None and vm.error_confirmar is None


def test_guardar_actualiza_supabase_y_mqtt():
    vm, auth, emqx, _, _ = _vm()
    _en_paso(vm, Paso.NUEVA_PASSWORD)
    vm.set_password(NUEVA)
    vm.set_confirmar_password(NUEVA)

    asyncio.run(vm.guardar_password())

    auth.confirmar_nueva_password.assert_called_once_with(NUEVA)
    emqx.crear_credencial.assert_called_once_with(CORREO, NUEVA)
    assert vm.paso == Paso.COMPLETADO
    assert vm.password == ""


def test_falla_de_emqx_no_impide_completar():
    vm, _, emqx, _, _ = _vm()
    emqx.crear_credencial.side_effect = RuntimeError("EMQX caído")
    _en_paso(vm, Paso.NUEVA_PASSWORD)
    vm.set_password(NUEVA)
    vm.set_confirmar_password(NUEVA)

    asyncio.run(vm.guardar_password())

    assert vm.paso == Paso.COMPLETADO


def test_password_repetida_permite_reintentar():
    vm, auth, emqx, _, _ = _vm()
    auth.confirmar_nueva_password.side_effect = PasswordRepetidaError("x")
    _en_paso(vm, Paso.NUEVA_PASSWORD)
    vm.set_password(NUEVA)
    vm.set_confirmar_password(NUEVA)

    asyncio.run(vm.guardar_password())

    assert vm.paso == Paso.NUEVA_PASSWORD
    assert vm.error_password == "Elige una contraseña distinta a la anterior"
    emqx.crear_credencial.assert_not_called()


def test_password_debil_muestra_la_razon_de_supabase():
    vm, auth, emqx, _, _ = _vm()
    auth.confirmar_nueva_password.side_effect = PasswordDebilError(["pwned"])
    _en_paso(vm, Paso.NUEVA_PASSWORD)
    vm.set_password(NUEVA)
    vm.set_confirmar_password(NUEVA)

    asyncio.run(vm.guardar_password())

    assert vm.paso == Paso.NUEVA_PASSWORD
    assert vm.error_password == (
        "Esta contraseña apareció en una filtración de datos conocida; elige otra"
    )
    emqx.crear_credencial.assert_not_called()


def test_sesion_de_recuperacion_expirada_regresa_al_paso_1():
    vm, auth, _, _, _ = _vm()
    auth.confirmar_nueva_password.side_effect = SinSesionError("x")
    _en_paso(vm, Paso.NUEVA_PASSWORD)
    vm.set_password(NUEVA)
    vm.set_confirmar_password(NUEVA)

    asyncio.run(vm.guardar_password())

    assert vm.paso == Paso.CORREO
    assert vm.alerta.titulo == "La verificación expiró"


@pytest.mark.parametrize(
    ("paso", "esperado", "cancela"),
    [
        (Paso.CODIGO, Paso.CORREO, False),
        (Paso.NUEVA_PASSWORD, Paso.CORREO, True),
    ],
)
def test_regresar(paso, esperado, cancela):
    vm, auth, _, login, _ = _vm()
    _en_paso(vm, paso)

    asyncio.run(vm.regresar())

    assert vm.paso == esperado
    assert auth.cancelar_recuperacion.called == cancela
    login.assert_not_called()


def test_regresar_desde_paso_1_va_al_login():
    vm, _, _, login, _ = _vm()
    asyncio.run(vm.regresar())
    login.assert_called_once()


def test_liberar_tras_verificar_cierra_la_sesion_temporal():
    vm, auth, _, _, _ = _vm()
    _en_paso(vm, Paso.NUEVA_PASSWORD)

    vm.liberar()

    auth.cancelar_recuperacion.assert_called_once()


def test_falla_de_red_al_verificar():
    vm, auth, _, _, _ = _vm()
    _en_paso(vm, Paso.CODIGO)
    auth.verificar_codigo_recuperacion.side_effect = ServicioNoDisponibleError("x")
    vm.set_codigo("123456")

    asyncio.run(vm.verificar_codigo())

    assert vm.alerta.titulo == "No se pudo conectar"
    assert not vm.mostrar_error_codigo
