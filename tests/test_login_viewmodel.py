import asyncio
from unittest.mock import MagicMock

from parking_app.services.auth_service import (
    CredencialesInvalidasError,
    CuentaBloqueadaError,
    CuentaInactivaError,
    DatosInvalidosError,
    DemasiadasSolicitudesError,
    ServicioNoDisponibleError,
)
from parking_app.viewmodels.login_viewmodel import LoginViewModel

CORREO = "alumno@itsx.edu.mx"


def _vm(auth=None):
    auth = auth or MagicMock()
    navegar = MagicMock()
    vm = LoginViewModel(auth, navegar, MagicMock(), MagicMock())
    return vm, auth, navegar


def _vm_con_datos(error=None):
    vm, auth, navegar = _vm()
    auth.iniciar_sesion.side_effect = error
    vm.set_correo(CORREO)
    vm.set_password("Segura#2026")
    return vm, auth, navegar


def test_valida_campos_antes_de_llamar_al_servicio():
    vm, auth, navegar = _vm()
    vm.set_correo("alumno@gmail.com")

    asyncio.run(vm.iniciar_sesion())

    assert vm.error_correo is not None
    assert vm.error_password == "Ingresa tu contraseña"
    assert vm.alerta is None
    auth.iniciar_sesion.assert_not_called()
    navegar.assert_not_called()


def test_login_exitoso_navega_y_olvida_password():
    vm, auth, navegar = _vm_con_datos()

    asyncio.run(vm.iniciar_sesion())

    auth.iniciar_sesion.assert_called_once_with(CORREO, "Segura#2026")
    navegar.assert_called_once()
    assert vm.alerta is None
    assert vm.password == ""
    assert not vm.cargando


def test_credenciales_invalidas_muestra_alerta_del_mockup():
    vm, _, navegar = _vm_con_datos(CredencialesInvalidasError(2))

    asyncio.run(vm.iniciar_sesion())

    assert vm.alerta.titulo == "Correo o contraseña incorrectos"
    assert vm.alerta.detalle == (
        "Te quedan 2 intentos. Después del tercer intento fallido, "
        "el acceso se bloqueará durante 3 minutos."
    )
    assert vm.resaltar_campos
    # Como en el mockup, los campos conservan lo escrito.
    assert vm.password == "Segura#2026"
    navegar.assert_not_called()


def test_ultimo_intento_en_singular():
    vm, _, _ = _vm_con_datos(CredencialesInvalidasError(1))

    asyncio.run(vm.iniciar_sesion())

    assert vm.alerta.detalle.startswith("Te queda 1 intento.")


def test_bloqueo_deshabilita_envio_y_muestra_cuenta_regresiva():
    async def escenario():
        vm, auth, _ = _vm_con_datos(CuentaBloqueadaError(180))
        auth.segundos_bloqueo_restantes.return_value = 179

        await vm.iniciar_sesion()

        assert vm.bloqueado
        assert not vm.puede_enviar
        assert vm.resaltar_campos
        assert vm.alerta.titulo == "Acceso bloqueado temporalmente"
        assert "3:00" in vm.alerta.detalle
        vm.liberar()

    asyncio.run(escenario())


def test_cuenta_inactiva_no_resalta_campos():
    vm, _, _ = _vm_con_datos(CuentaInactivaError("x"))

    asyncio.run(vm.iniciar_sesion())

    assert vm.alerta.titulo == "Cuenta inactiva"
    assert not vm.resaltar_campos


def test_falla_de_red_muestra_alerta_de_conexion():
    vm, _, _ = _vm_con_datos(ServicioNoDisponibleError("timeout"))

    asyncio.run(vm.iniciar_sesion())

    assert vm.alerta.titulo == "No se pudo conectar"


def test_datos_rechazados_por_formato_no_son_falla_de_conexion():
    vm, _, _ = _vm_con_datos(DatosInvalidosError("Unable to validate email address"))

    asyncio.run(vm.iniciar_sesion())

    assert vm.alerta.titulo == "Datos no válidos"
    assert not vm.bloqueado and not vm.resaltar_campos
    assert vm.password == "Segura#2026"


def test_limite_de_peticiones_muestra_espera_y_no_bloquea():
    vm, _, _ = _vm_con_datos(DemasiadasSolicitudesError("429"))

    asyncio.run(vm.iniciar_sesion())

    assert vm.alerta.titulo == "Demasiados intentos"
    assert vm.alerta.detalle == "Espera un momento antes de volver a intentarlo."
    assert not vm.bloqueado and not vm.resaltar_campos


def test_nuevo_intento_limpia_la_alerta_anterior():
    vm, auth, _ = _vm_con_datos(CredencialesInvalidasError(2))
    asyncio.run(vm.iniciar_sesion())

    auth.iniciar_sesion.side_effect = None
    asyncio.run(vm.iniciar_sesion())

    assert vm.alerta is None


def test_notifica_a_la_vista():
    vm, _, _ = _vm()
    listener = MagicMock()
    vm.add_listener(listener)

    vm.set_correo("a")

    listener.assert_called_once()
