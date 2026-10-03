from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from supabase_auth.errors import (
    AuthApiError,
    AuthSessionMissingError,
    AuthUnknownError,
    AuthWeakPasswordError,
)

from parking_app.models.usuario import MedioTransporte, Usuario
from parking_app.services.auth_service import (
    AuthService,
    CodigoInvalidoError,
    ControlIntentos,
    CorreoYaRegistradoError,
    PasswordRepetidaError,
    CredencialesInvalidasError,
    CuentaBloqueadaError,
    CuentaInactivaError,
    DatosInvalidosError,
    DemasiadasSolicitudesError,
    LimiteCorreosError,
    PasswordDebilError,
    ServicioNoDisponibleError,
    SinSesionError,
)

CORREO = "alumno@itsx.edu.mx"


class RelojFalso:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


def _fila_usuario(estado="activo"):
    return {
        "id_usuario": "uid-1",
        "nombre": "Ana",
        "apellido_paterno": "Pérez",
        "apellido_materno": "López",
        "correo_institucional": CORREO,
        "medio_transporte": "vehiculo",
        "estado_cuenta": estado,
    }


def _cliente(fila=None):
    cliente = MagicMock()
    cliente.auth.sign_in_with_password.return_value = SimpleNamespace(
        user=SimpleNamespace(id="uid-1"),
        session=SimpleNamespace(access_token="tok"),
    )
    consulta = cliente.table.return_value.select.return_value.eq.return_value.limit.return_value
    consulta.execute.return_value = SimpleNamespace(data=[fila or _fila_usuario()])
    return cliente


def _servicio(cliente, reloj=None):
    control = ControlIntentos(reloj=reloj or RelojFalso())
    return AuthService(cliente_factory=lambda: cliente, control_intentos=control)


def _error_credenciales():
    return AuthApiError("Invalid login credentials", 400, "invalid_credentials")


def test_login_exitoso_guarda_sesion_y_credenciales_mqtt():
    servicio = _servicio(_cliente())

    sesion = servicio.iniciar_sesion("  Alumno@ITSX.edu.mx ", "Segura#2026")

    assert sesion.id_usuario == "uid-1"
    assert servicio.hay_sesion_activa
    assert servicio.usuario_actual.nombre == "Ana"
    assert servicio.credenciales_mqtt.usuario == CORREO
    assert servicio.credenciales_mqtt.password == "Segura#2026"


def test_descartar_password_mqtt_conserva_el_correo_hasta_cerrar_sesion():
    servicio = _servicio(_cliente())
    servicio.iniciar_sesion(CORREO, "Segura#2026")

    servicio.descartar_password_mqtt()

    assert servicio.credenciales_mqtt is None
    assert servicio.correo_actual == CORREO
    assert servicio.hay_sesion_activa

    servicio.cerrar_sesion()
    assert servicio.correo_actual is None


def test_bloqueo_tras_tres_fallos_y_desbloqueo_a_los_tres_minutos():
    cliente = _cliente()
    cliente.auth.sign_in_with_password.side_effect = _error_credenciales()
    reloj = RelojFalso()
    servicio = _servicio(cliente, reloj)

    with pytest.raises(CredencialesInvalidasError) as e1:
        servicio.iniciar_sesion(CORREO, "mala")
    assert e1.value.intentos_restantes == 2
    with pytest.raises(CredencialesInvalidasError):
        servicio.iniciar_sesion(CORREO, "mala")
    with pytest.raises(CuentaBloqueadaError) as e3:
        servicio.iniciar_sesion(CORREO, "mala")
    assert e3.value.segundos_restantes == 180

    # Bloqueado: ni siquiera se consulta a Supabase.
    cliente.auth.sign_in_with_password.reset_mock()
    reloj.ahora += 179
    with pytest.raises(CuentaBloqueadaError):
        servicio.iniciar_sesion(CORREO, "Segura#2026")
    cliente.auth.sign_in_with_password.assert_not_called()

    reloj.ahora += 1
    cliente.auth.sign_in_with_password.side_effect = None
    servicio.iniciar_sesion(CORREO, "Segura#2026")
    assert servicio.hay_sesion_activa


def test_falla_de_red_no_cuenta_como_intento():
    cliente = _cliente()
    cliente.auth.sign_in_with_password.side_effect = AuthApiError("boom", 500, None)
    servicio = _servicio(cliente)

    for _ in range(5):
        with pytest.raises(ServicioNoDisponibleError):
            servicio.iniciar_sesion(CORREO, "x")
    assert servicio.segundos_bloqueo_restantes(CORREO) == 0


@pytest.mark.parametrize(
    ("error", "esperado"),
    [
        (AuthApiError("Unable to validate email address", 400, "email_address_invalid"),
         DatosInvalidosError),
        (AuthApiError("Validation failed", 400, "validation_failed"), DatosInvalidosError),
        (AuthApiError("User is banned", 400, "user_banned"), CuentaInactivaError),
        (AuthApiError("captcha protection", 400, "captcha_failed"), ServicioNoDisponibleError),
        (AuthApiError("Email logins are disabled", 422, "email_provider_disabled"),
         ServicioNoDisponibleError),
        (AuthApiError("Unauthorized", 401, None), ServicioNoDisponibleError),
    ],
)
def test_solo_invalid_credentials_cuenta_como_intento(error, esperado):
    cliente = _cliente()
    cliente.auth.sign_in_with_password.side_effect = error
    servicio = _servicio(cliente)

    for _ in range(5):
        with pytest.raises(esperado):
            servicio.iniciar_sesion(CORREO, "x")
    assert servicio.segundos_bloqueo_restantes(CORREO) == 0
    assert not servicio.hay_sesion_activa


def test_error_de_configuracion_deja_el_codigo_en_el_log(caplog):
    cliente = _cliente()
    cliente.auth.sign_in_with_password.side_effect = AuthApiError(
        "captcha protection: request disallowed", 400, "captcha_failed"
    )
    servicio = _servicio(cliente)

    with pytest.raises(ServicioNoDisponibleError):
        servicio.iniciar_sesion(CORREO, "x")

    assert "captcha_failed" in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        AuthApiError("Request rate limit reached", 429, "over_request_rate_limit"),
        AuthApiError("Too many requests", 429, None),
    ],
)
def test_limite_de_peticiones_en_login_no_cuenta_como_intento(error):
    cliente = _cliente()
    cliente.auth.sign_in_with_password.side_effect = error
    servicio = _servicio(cliente)

    for _ in range(5):
        with pytest.raises(DemasiadasSolicitudesError):
            servicio.iniciar_sesion(CORREO, "x")
    assert servicio.segundos_bloqueo_restantes(CORREO) == 0


def test_error_desconocido_deja_la_causa_real_en_el_log(caplog):
    cliente = _cliente()
    causa = ValueError("Expecting value: line 1 column 1 (<html>…)")
    cliente.auth.sign_in_with_password.side_effect = AuthUnknownError("502 Bad Gateway", causa)
    servicio = _servicio(cliente)

    with pytest.raises(ServicioNoDisponibleError):
        servicio.iniciar_sesion(CORREO, "x")

    assert "Expecting value" in caplog.text
    assert "502 Bad Gateway" in caplog.text


def test_cuenta_inactiva_no_inicia_sesion():
    cliente = _cliente(_fila_usuario(estado="inactivo"))
    servicio = _servicio(cliente)

    with pytest.raises(CuentaInactivaError):
        servicio.iniciar_sesion(CORREO, "Segura#2026")
    assert not servicio.hay_sesion_activa
    cliente.auth.sign_out.assert_called_once()


def _usuario_nuevo():
    return Usuario(
        id_usuario="",
        nombre=" Ana ",
        apellido_paterno="Pérez",
        apellido_materno="",
        correo_institucional=" Ana@ITSX.edu.mx",
        medio_transporte=MedioTransporte.VEHICULO,
    )


def _respuesta_sign_up(session=None, identities=("email",)):
    return SimpleNamespace(
        user=SimpleNamespace(id="uid-nuevo", identities=list(identities)),
        session=session,
    )


def test_registrar_envia_metadatos_para_el_trigger_y_no_inserta_en_la_tabla():
    cliente = _cliente()
    cliente.auth.sign_up.return_value = _respuesta_sign_up()
    servicio = _servicio(cliente)

    resultado = servicio.registrar(_usuario_nuevo(), "Segura#2026")

    credenciales = cliente.auth.sign_up.call_args.args[0]
    assert credenciales["email"] == "ana@itsx.edu.mx"
    assert credenciales["options"]["data"] == {
        "nombre": "Ana",
        "apellido_paterno": "Pérez",
        "apellido_materno": None,
        "medio_transporte": "vehiculo",
    }
    cliente.table.assert_not_called()
    assert resultado.requiere_confirmacion
    assert resultado.usuario.id_usuario == "uid-nuevo"


def test_registrar_sin_confirmacion_cierra_la_sesion_abierta():
    cliente = _cliente()
    cliente.auth.sign_up.return_value = _respuesta_sign_up(session=SimpleNamespace())
    servicio = _servicio(cliente)

    resultado = servicio.registrar(_usuario_nuevo(), "Segura#2026")

    assert not resultado.requiere_confirmacion
    cliente.auth.sign_out.assert_called_once()


def test_registrar_correo_duplicado_oculto_por_supabase():
    cliente = _cliente()
    cliente.auth.sign_up.return_value = _respuesta_sign_up(identities=())
    servicio = _servicio(cliente)

    with pytest.raises(CorreoYaRegistradoError):
        servicio.registrar(_usuario_nuevo(), "Segura#2026")


@pytest.mark.parametrize(
    ("error", "esperado"),
    [
        (AuthApiError("exists", 422, "user_already_exists"), CorreoYaRegistradoError),
        (AuthApiError("rate", 429, "over_email_send_rate_limit"), LimiteCorreosError),
        (AuthApiError("Database error saving new user", 500, "unexpected_failure"),
         ServicioNoDisponibleError),
    ],
)
def test_registrar_traduce_errores(error, esperado):
    cliente = _cliente()
    cliente.auth.sign_up.side_effect = error
    servicio = _servicio(cliente)

    with pytest.raises(esperado):
        servicio.registrar(_usuario_nuevo(), "Segura#2026")


@pytest.mark.parametrize(
    ("error", "campo"),
    [
        # Supabase no acepta enviar el correo de confirmación a esa dirección.
        (AuthApiError('Email address "ana@itsx.edu.mx" is invalid', 400,
                      "email_address_invalid"), "correo"),
        # Respuesta real observada con un correo sin formato.
        (AuthApiError("Unable to validate email address: invalid format", 400,
                      "validation_failed"), None),
    ],
)
def test_registrar_correo_rechazado_indica_el_campo(error, campo):
    cliente = _cliente()
    cliente.auth.sign_up.side_effect = error
    servicio = _servicio(cliente)

    with pytest.raises(DatosInvalidosError) as e:
        servicio.registrar(_usuario_nuevo(), "Segura#2026")
    assert e.value.campo == campo


def test_registrar_password_debil_no_es_falla_de_conexion():
    cliente = _cliente()
    cliente.auth.sign_up.side_effect = AuthWeakPasswordError(
        "weak", 422, ["length", "pwned"]
    )
    servicio = _servicio(cliente)

    with pytest.raises(PasswordDebilError) as e:
        servicio.registrar(_usuario_nuevo(), "Segura#2026")
    assert e.value.razones == ["length", "pwned"]


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("nombre", "Ana2"), ("apellido_paterno", "P3rez"), ("apellido_materno", "López 1")],
)
def test_registrar_rechaza_numeros_en_nombres_sin_llamar_a_supabase(campo, valor):
    cliente = _cliente()
    servicio = _servicio(cliente)
    usuario = _usuario_nuevo()
    setattr(usuario, campo, valor)

    with pytest.raises(DatosInvalidosError) as e:
        servicio.registrar(usuario, "Segura#2026")
    assert e.value.campo == campo
    cliente.auth.sign_up.assert_not_called()


def test_verificar_codigo_usa_tipo_recovery():
    cliente = _cliente()
    cliente.auth.verify_otp.return_value = SimpleNamespace(session=SimpleNamespace())
    servicio = _servicio(cliente)

    servicio.verificar_codigo_recuperacion(" Ana@ITSX.edu.mx", " 123456 ")

    cliente.auth.verify_otp.assert_called_once_with(
        {"email": "ana@itsx.edu.mx", "token": "123456", "type": "recovery"}
    )


def test_codigo_vencido():
    cliente = _cliente()
    cliente.auth.verify_otp.side_effect = AuthApiError("expired", 403, "otp_expired")
    servicio = _servicio(cliente)

    with pytest.raises(CodigoInvalidoError):
        servicio.verificar_codigo_recuperacion(CORREO, "000000")


def test_password_repetida_no_cierra_la_sesion_de_recuperacion():
    cliente = _cliente()
    cliente.auth.update_user.side_effect = AuthApiError("same", 422, "same_password")
    servicio = _servicio(cliente)

    with pytest.raises(PasswordRepetidaError):
        servicio.confirmar_nueva_password("Nueva#2026")
    cliente.auth.sign_out.assert_not_called()


def test_nueva_password_debil_conserva_razones_y_la_sesion():
    cliente = _cliente()
    cliente.auth.update_user.side_effect = AuthWeakPasswordError("weak", 422, ["length"])
    servicio = _servicio(cliente)

    with pytest.raises(PasswordDebilError) as e:
        servicio.confirmar_nueva_password("Nueva#2026")
    assert e.value.razones == ["length"]
    cliente.auth.sign_out.assert_not_called()


def test_nueva_password_sin_sesion_de_recuperacion():
    cliente = _cliente()
    cliente.auth.update_user.side_effect = AuthSessionMissingError()
    servicio = _servicio(cliente)

    with pytest.raises(SinSesionError):
        servicio.confirmar_nueva_password("Nueva#2026")


def test_nueva_password_exitosa_cierra_la_sesion_de_recuperacion():
    cliente = _cliente()
    servicio = _servicio(cliente)

    servicio.confirmar_nueva_password("Nueva#2026")

    cliente.auth.update_user.assert_called_once_with({"password": "Nueva#2026"})
    cliente.auth.sign_out.assert_called_once()


def test_limite_al_solicitar_codigo():
    cliente = _cliente()
    cliente.auth.reset_password_for_email.side_effect = AuthApiError(
        "rate", 429, "over_email_send_rate_limit"
    )
    servicio = _servicio(cliente)

    with pytest.raises(LimiteCorreosError):
        servicio.solicitar_restablecimiento(CORREO)


def test_login_registra_sesion_con_huella_del_token():
    cliente = _cliente()
    servicio = _servicio(cliente)

    sesion = servicio.iniciar_sesion(CORREO, "Segura#2026")

    cliente.table.assert_any_call("sesiones")
    fila = cliente.table.return_value.insert.call_args.args[0]
    assert fila["id_sesion"] == sesion.id_sesion
    assert fila["id_usuario"] == "uid-1"
    assert fila["estado"] == "activo"
    assert fila["token"] != "tok" and len(fila["token"]) == 64


def test_falla_al_registrar_sesion_no_impide_el_login():
    cliente = _cliente()
    cliente.table.return_value.insert.return_value.execute.side_effect = Exception("RLS")
    servicio = _servicio(cliente)

    servicio.iniciar_sesion(CORREO, "Segura#2026")

    assert servicio.hay_sesion_activa


def test_cerrar_sesion_cierra_registro_antes_de_sign_out():
    cliente = _cliente()
    servicio = _servicio(cliente)
    sesion = servicio.iniciar_sesion(CORREO, "Segura#2026")
    orden = []
    cliente.table.return_value.update.side_effect = lambda datos: orden.append(("update", datos)) or MagicMock()
    cliente.auth.sign_out.side_effect = lambda: orden.append(("sign_out", None))

    servicio.cerrar_sesion()

    assert [o[0] for o in orden] == ["update", "sign_out"]
    assert orden[0][1]["estado"] == "inactivo"
    assert orden[0][1]["fecha_cierre_sesion"]
    assert not sesion.activa
    assert not servicio.hay_sesion_activa
    assert servicio.credenciales_mqtt is None
