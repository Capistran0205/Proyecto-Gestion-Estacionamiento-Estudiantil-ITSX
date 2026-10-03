import asyncio
from unittest.mock import MagicMock

import pytest

from parking_app.models.usuario import MedioTransporte, Usuario
from parking_app.services.auth_service import (
    CorreoYaRegistradoError,
    DatosInvalidosError,
    LimiteCorreosError,
    PasswordDebilError,
    ResultadoRegistro,
    ServicioNoDisponibleError,
)
from parking_app.viewmodels.alerta import mensaje_password_debil
from parking_app.viewmodels.registro_viewmodel import RegistroViewModel

CORREO = "ana.perez@itsx.edu.mx"
PASSWORD = "Segura#2026"


def _resultado(requiere_confirmacion=True):
    usuario = Usuario("uid", "Ana", "Pérez", None, CORREO, MedioTransporte.VEHICULO)
    return ResultadoRegistro(usuario=usuario, requiere_confirmacion=requiere_confirmacion)


def _vm():
    auth, emqx = MagicMock(), MagicMock()
    auth.registrar.return_value = _resultado()
    vm = RegistroViewModel(auth, emqx, MagicMock(), MagicMock())
    return vm, auth, emqx


def _llenar(vm):
    vm.set_nombre("Ana")
    vm.set_apellido_paterno("Pérez")
    vm.set_medio_transporte(MedioTransporte.VEHICULO)
    vm.set_correo(CORREO)
    vm.set_password(PASSWORD)
    vm.set_confirmar_password(PASSWORD)


def test_sin_errores_antes_del_primer_envio():
    vm, _, _ = _vm()
    vm.set_correo("x@gmail.com")
    assert vm.alerta is None
    assert vm.error("correo") is None


def test_campos_faltantes_como_el_mockup():
    vm, auth, _ = _vm()
    vm.set_nombre("Ana")
    vm.set_apellido_materno("López")
    vm.set_correo(CORREO)

    asyncio.run(vm.crear_cuenta())

    assert vm.alerta.titulo == "Faltan 4 campos por completar"
    assert vm.alerta.detalle == "Revisa los campos marcados para poder crear tu cuenta."
    assert vm.error("nombre") is None
    assert vm.error("apellido_paterno") == "Campo obligatorio"
    assert vm.error("medio_transporte") == "Selecciona tu medio de transporte"
    assert vm.error("correo") is None
    assert vm.error("password") == "Escribe una contraseña"
    assert vm.error("confirmar_password") == "Confirma tu contraseña"
    auth.registrar.assert_not_called()


def test_apellido_materno_es_opcional():
    vm, auth, _ = _vm()
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    auth.registrar.assert_called_once()
    assert vm.registro_completado


def test_errores_se_actualizan_al_escribir_tras_el_primer_envio():
    vm, _, _ = _vm()
    asyncio.run(vm.crear_cuenta())
    assert vm.error("nombre") == "Campo obligatorio"

    vm.set_nombre("Ana")

    assert vm.error("nombre") is None
    assert vm.alerta.titulo == "Faltan 5 campos por completar"


def test_una_sola_falta_en_singular():
    vm, _, _ = _vm()
    _llenar(vm)
    vm.set_apellido_paterno("")

    asyncio.run(vm.crear_cuenta())

    assert vm.alerta.titulo == "Falta 1 campo por completar"


@pytest.mark.parametrize(
    ("password", "confirmar", "campo", "mensaje"),
    [
        ("debil", "debil", "password", "Tu contraseña no cumple los requisitos"),
        (PASSWORD, "Otra#2026", "confirmar_password", "Las contraseñas no coinciden"),
    ],
)
def test_errores_de_formato_sin_campos_faltantes(password, confirmar, campo, mensaje):
    vm, auth, _ = _vm()
    _llenar(vm)
    vm.set_password(password)
    vm.set_confirmar_password(confirmar)

    asyncio.run(vm.crear_cuenta())

    assert vm.error(campo) == mensaje
    assert vm.alerta.titulo == "Revisa los campos marcados"
    auth.registrar.assert_not_called()


@pytest.mark.parametrize(
    ("setter", "campo"),
    [
        ("set_nombre", "nombre"),
        ("set_apellido_paterno", "apellido_paterno"),
        ("set_apellido_materno", "apellido_materno"),
    ],
)
def test_numeros_en_nombre_o_apellidos_no_se_registran(setter, campo):
    vm, auth, _ = _vm()
    _llenar(vm)
    getattr(vm, setter)("Ana2")

    asyncio.run(vm.crear_cuenta())

    assert vm.error(campo) == "Solo se permiten letras, sin números ni símbolos"
    assert vm.alerta.titulo == "Revisa los campos marcados"
    auth.registrar.assert_not_called()


def test_nombres_se_envian_sin_espacios_sobrantes():
    vm, auth, _ = _vm()
    _llenar(vm)
    vm.set_nombre("  Ana   Sofía ")

    asyncio.run(vm.crear_cuenta())

    usuario, _ = auth.registrar.call_args.args
    assert usuario.nombre == "Ana Sofía"


def test_correo_de_otro_dominio():
    vm, _, _ = _vm()
    _llenar(vm)
    vm.set_correo("ana@gmail.com")

    asyncio.run(vm.crear_cuenta())

    assert "institucional" in vm.error("correo")


def test_requisitos_de_password_en_vivo():
    vm, _, _ = _vm()
    vm.set_password("abc1")
    assert [ok for _, ok in vm.requisitos_password] == [True, False, True, True, False]
    vm.set_password(PASSWORD)
    assert all(ok for _, ok in vm.requisitos_password)


def test_registro_exitoso_aprovisiona_mqtt_y_pide_confirmar_correo():
    vm, auth, emqx = _vm()
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    usuario, password = auth.registrar.call_args.args
    assert usuario.medio_transporte is MedioTransporte.VEHICULO
    assert password == PASSWORD
    emqx.crear_credencial.assert_called_once_with(CORREO, PASSWORD)
    assert vm.registro_completado
    assert vm.titulo_exito == "¡Cuenta creada!"
    assert CORREO in vm.detalle_exito and "Confirma" in vm.detalle_exito
    assert vm.password == "" and vm.confirmar_password == ""


def test_sin_confirmacion_usa_el_texto_del_mockup():
    vm, auth, _ = _vm()
    auth.registrar.return_value = _resultado(requiere_confirmacion=False)
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    assert vm.detalle_exito == (
        "Tu registro se completó. Ya puedes iniciar sesión con tu correo institucional."
    )


def test_falla_de_emqx_no_bloquea_el_registro():
    vm, _, emqx = _vm()
    emqx.crear_credencial.side_effect = RuntimeError("EMQX caído")
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    assert vm.registro_completado


def test_correo_duplicado_muestra_aviso_y_se_limpia_al_editar():
    vm, auth, emqx = _vm()
    auth.registrar.side_effect = CorreoYaRegistradoError("dup")
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    assert vm.correo_duplicado
    assert vm.alerta is None
    assert not vm.registro_completado
    emqx.crear_credencial.assert_not_called()

    vm.set_correo("otra@itsx.edu.mx")
    assert not vm.correo_duplicado


def test_password_debil_para_supabase_marca_el_campo_hasta_cambiarla():
    vm, auth, emqx = _vm()
    auth.registrar.side_effect = PasswordDebilError(["length"])
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    mensaje = "Esta contraseña es demasiado corta; elige otra"
    assert vm.error("password") == mensaje
    assert vm.alerta.titulo == "Revisa los campos marcados"
    assert not vm.registro_completado
    emqx.crear_credencial.assert_not_called()

    vm.set_nombre("Ana Sofía")  # editar otro campo no borra el aviso
    assert vm.error("password") == mensaje

    vm.set_password("Otra#Segura2026")
    assert vm.error("password") is None


def test_correo_rechazado_por_supabase_marca_el_campo_hasta_editarlo():
    vm, auth, emqx = _vm()
    mensaje = "No es posible enviar correos a esta dirección. Revisa que esté bien escrita."
    auth.registrar.side_effect = DatosInvalidosError(mensaje, "correo")
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    assert vm.error("correo") == mensaje
    assert vm.alerta.titulo == "Revisa los campos marcados"
    assert not vm.registro_completado
    emqx.crear_credencial.assert_not_called()

    vm.set_password(PASSWORD)  # editar otro campo no borra el aviso
    assert vm.error("correo") == mensaje

    vm.set_correo("ana.perez2@itsx.edu.mx")
    assert vm.error("correo") is None
    assert vm.alerta is None


def test_rechazo_sin_campo_muestra_alerta_general_sin_marcar_campos():
    vm, auth, _ = _vm()
    auth.registrar.side_effect = DatosInvalidosError("Unable to validate email address")
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    assert vm.alerta.titulo == "No se pudieron validar tus datos"
    assert not any(vm.errores.values())


@pytest.mark.parametrize(
    ("razones", "mensaje"),
    [
        ([], "Esta contraseña es demasiado débil; prueba con una más larga"),
        (["length", "characters"],
         "Esta contraseña es demasiado corta y le faltan tipos de caracteres; elige otra"),
        (["desconocida"], "Esta contraseña es demasiado débil; prueba con una más larga"),
    ],
)
def test_mensaje_password_debil(razones, mensaje):
    assert mensaje_password_debil(razones) == mensaje


@pytest.mark.parametrize(
    ("error", "titulo"),
    [
        (LimiteCorreosError("x"), "Demasiados registros por ahora"),
        (ServicioNoDisponibleError("x"), "No se pudo crear tu cuenta"),
    ],
)
def test_errores_del_servicio(error, titulo):
    vm, auth, _ = _vm()
    auth.registrar.side_effect = error
    _llenar(vm)

    asyncio.run(vm.crear_cuenta())

    assert vm.alerta.titulo == titulo
    assert not vm.cargando
