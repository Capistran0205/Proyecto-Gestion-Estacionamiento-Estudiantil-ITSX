"""Autenticación contra Supabase Auth + tabla `usuario`.

Todas las llamadas son bloqueantes (red): los ViewModels deben invocarlas
fuera del hilo de UI (p. ej. con `asyncio.to_thread`).
"""

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

import httpx
from supabase import Client
from supabase_auth.errors import (
    AuthApiError,
    AuthError,
    AuthSessionMissingError,
    AuthUnknownError,
    AuthWeakPasswordError,
)

from parking_app.core.config import MAX_INTENTOS_LOGIN, SEGUNDOS_BLOQUEO_LOGIN
from parking_app.core.validadores import (
    normalizar_correo,
    normalizar_nombre,
    validar_nombre_apellido_persona,
)
from parking_app.models.sesion import EstadoSesion, Sesion
from parking_app.models.usuario import Usuario

logger = logging.getLogger(__name__)

TABLA_USUARIOS = "usuarios"
TABLA_SESIONES = "sesiones"


# --- Errores de dominio (los ViewModels traducen estos a mensajes de UI) ---


class AuthServiceError(Exception):
    """Error base del servicio de autenticación."""


class CredencialesInvalidasError(AuthServiceError):
    def __init__(self, intentos_restantes: int) -> None:
        super().__init__("Correo o contraseña incorrectos")
        self.intentos_restantes = intentos_restantes


class CuentaBloqueadaError(AuthServiceError):
    def __init__(self, segundos_restantes: int) -> None:
        super().__init__("Demasiados intentos fallidos")
        self.segundos_restantes = segundos_restantes


class CuentaInactivaError(AuthServiceError):
    pass


class CorreoNoConfirmadoError(AuthServiceError):
    pass


class CorreoYaRegistradoError(AuthServiceError):
    pass


class LimiteCorreosError(AuthServiceError):
    """Supabase limita cuántos correos de confirmación envía por hora."""


class DemasiadasSolicitudesError(AuthServiceError):
    """Supabase limitó las peticiones (429): no cuenta como intento fallido."""


class CodigoInvalidoError(AuthServiceError):
    pass


class SinSesionError(AuthServiceError):
    pass


class PasswordRepetidaError(AuthServiceError):
    pass


class PasswordDebilError(AuthServiceError):
    """La política de contraseñas de Supabase la rechazó.

    `razones` viene de Supabase: "length", "characters" y/o "pwned".
    """

    def __init__(self, razones: Iterable[str] | None = None) -> None:
        super().__init__("La contraseña es demasiado débil")
        self.razones = list(razones or ())


class DatosInvalidosError(AuthServiceError):
    """Datos con formato no permitido: números en el nombre o un correo que
    Supabase rechaza al registrarse, o datos de acceso mal formados en el login.

    `campo` indica qué campo del formulario marcar ("nombre", "correo"…); None si
    Supabase no lo precisa. El mensaje está listo para mostrarse bajo el campo.
    """

    def __init__(self, mensaje: str, campo: str | None = None) -> None:
        super().__init__(mensaje)
        self.campo = campo


class ServicioNoDisponibleError(AuthServiceError):
    """Falla de red o del servidor: no cuenta como intento fallido."""


def _no_disponible(e: Exception) -> ServicioNoDisponibleError:
    """Traduce una falla de red/servidor, dejando en el log la causa real."""
    if isinstance(e, AuthApiError):
        # Respuesta sin traducción propia (captcha_failed, email_provider_disabled,
        # hook_timeout…): casi siempre es configuración del panel de Supabase.
        logger.warning("Supabase Auth respondió %s (%s): %s", e.status, e.code, e.message)
    elif isinstance(e, AuthUnknownError):
        # Respuesta que la librería no supo interpretar (p. ej. HTML de un proxy):
        # sin esto el log solo diría "servicio no disponible".
        logger.warning(
            "Respuesta inesperada de Supabase Auth: %s (causa: %r)",
            e.message,
            e.original_error,
        )
    return ServicioNoDisponibleError(str(e))


# --- Control de intentos de login (Supabase no lo provee) ---

# Clase representativa para el control de intentos, cuenta los intentos fallidos de cada correo y bloque 3 minutos después de 3 fallos
class ControlIntentos:
    """Cuenta intentos fallidos por correo y bloquea tras el máximo."""

    def __init__(
        self,
        max_intentos: int = MAX_INTENTOS_LOGIN,
        segundos_bloqueo: int = SEGUNDOS_BLOQUEO_LOGIN,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_intentos
        self._bloqueo = segundos_bloqueo
        self._reloj = reloj
        self._fallos: dict[str, int] = {}
        self._bloqueado_hasta: dict[str, float] = {}

    def segundos_restantes(self, correo: str) -> int:
        hasta = self._bloqueado_hasta.get(correo)
        if hasta is None:
            return 0
        restante = hasta - self._reloj()
        if restante <= 0:
            # El bloqueo expiró: se empieza de cero.
            del self._bloqueado_hasta[correo]
            self._fallos.pop(correo, None)
            return 0
        return int(restante + 0.999)

    def registrar_fallo(self, correo: str) -> int:
        """Registra un fallo y devuelve cuántos intentos quedan (0 = bloqueado)."""
        fallos = self._fallos.get(correo, 0) + 1
        self._fallos[correo] = fallos
        if fallos >= self._max:
            self._bloqueado_hasta[correo] = self._reloj() + self._bloqueo
            return 0
        return self._max - fallos

    def reiniciar(self, correo: str) -> None:
        self._fallos.pop(correo, None)
        self._bloqueado_hasta.pop(correo, None)

# Clase representativa la cual representa el resultado obtenido del registro del usuario,
# por lo tanto contiene maneja el usuario creado previamente y si requiere confirmación lo cual es posible
# para determinar si Supabase mando o no mandó un correo de confirmación.
@dataclass(frozen=True)
class ResultadoRegistro:
    usuario: Usuario
    # True si Supabase envió un correo de confirmación antes de permitir el login.
    requiere_confirmacion: bool

# Clase representativa para mantener las credenciales de acceso al servicio MQTT por autenticación
@dataclass(frozen=True)
class CredencialesMqtt:
    """Credenciales del usuario para el broker; solo en memoria, nunca persistidas."""

    usuario: str
    password: str

# Clase representativa para el login/registro de usuarios, implementado métodos de Supabase Authentication
class AuthService:
    def __init__(
        self,
        cliente_factory: Callable[[], Client] | None = None,
        control_intentos: ControlIntentos | None = None,
    ) -> None:
        if cliente_factory is None:
            from parking_app.services.supabase_client import get_supabase

            cliente_factory = get_supabase
        self._cliente_factory = cliente_factory
        self._intentos = control_intentos or ControlIntentos()
        self._sesion: Sesion | None = None
        self._usuario: Usuario | None = None
        self._correo: str | None = None
        self._credenciales_mqtt: CredencialesMqtt | None = None

    @property
    def _cliente(self) -> Client:
        return self._cliente_factory()

    # --- Estado de sesión ---

    @property
    def sesion_actual(self) -> Sesion | None:
        return self._sesion if self._sesion and self._sesion.activa else None

    @property
    def hay_sesion_activa(self) -> bool:
        return self.sesion_actual is not None

    @property
    def usuario_actual(self) -> Usuario | None:
        return self._usuario

    @property
    def correo_actual(self) -> str | None:
        """Correo con el que se inició sesión (dura toda la sesión)."""
        return self._correo

    @property
    def credenciales_mqtt(self) -> CredencialesMqtt | None:
        """Correo y contraseña para el broker; None tras descartar_password_mqtt()."""
        return self._credenciales_mqtt

    def descartar_password_mqtt(self) -> None:
        """Borra de memoria la contraseña del login.

        Solo hace falta hasta que el broker la acepta (paho conserva su propia
        copia para reconectar) o hasta intentar resincronizarla con EMQX.
        """
        self._credenciales_mqtt = None

    def segundos_bloqueo_restantes(self, correo: str) -> int:
        return self._intentos.segundos_restantes(normalizar_correo(correo))

    # --- Login ---

    def iniciar_sesion(self, correo: str, contraseña: str) -> Sesion:
        correo = normalizar_correo(correo)

        restantes = self._intentos.segundos_restantes(correo)
        if restantes > 0:
            raise CuentaBloqueadaError(restantes)

        try:
            respuesta = self._cliente.auth.sign_in_with_password(
                {"email": correo, "password": contraseña}
            )
        except AuthApiError as e:
            if e.code == "email_not_confirmed":
                raise CorreoNoConfirmadoError(
                    "Confirma tu correo antes de iniciar sesión"
                ) from e
            # Solo una contraseña o correo incorrectos suman al bloqueo; los demás
            # 400 no son un intento fallido.
            if e.code == "invalid_credentials":
                intentos = self._intentos.registrar_fallo(correo)
                if intentos == 0:
                    raise CuentaBloqueadaError(
                        self._intentos.segundos_restantes(correo)
                    ) from e
                raise CredencialesInvalidasError(intentos) from e
            if e.code == "user_banned":
                # Suspensión desde el panel de Supabase: equivale a cuenta inactiva.
                raise CuentaInactivaError("Tu cuenta está suspendida") from e
            if e.code in ("validation_failed", "email_address_invalid"):
                raise DatosInvalidosError(e.message) from e
            if e.code == "over_request_rate_limit" or e.status == 429:
                raise DemasiadasSolicitudesError("Demasiadas solicitudes") from e
            raise _no_disponible(e) from e
        except (AuthError, httpx.HTTPError) as e:
            raise _no_disponible(e) from e

        if respuesta.user is None or respuesta.session is None:
            raise ServicioNoDisponibleError("Supabase no devolvió una sesión")

        usuario = self._obtener_usuario(respuesta.user.id)
        if usuario is not None and not usuario.activo:
            self._cerrar_sesion_remota()
            raise CuentaInactivaError("Tu cuenta está inactiva")

        self._intentos.reiniciar(correo)
        self._usuario = usuario
        self._correo = correo
        self._credenciales_mqtt = CredencialesMqtt(usuario=correo, password=contraseña)
        self._sesion = Sesion(
            id_usuario=respuesta.user.id,
            token=respuesta.session.access_token,
            fecha_acceso=datetime.now().astimezone(),
        )
        self._registrar_sesion(self._sesion)
        return self._sesion

    def cerrar_sesion(self) -> None:
        # Primero se cierra la fila en `sesiones`: RLS exige seguir autenticado.
        if self._sesion is not None:
            self._sesion.fecha_cierre_sesion = datetime.now().astimezone()
            self._sesion.estado = EstadoSesion.INACTIVO
            self._cerrar_registro_sesion(self._sesion)
        self._cerrar_sesion_remota()
        self._sesion = None
        self._usuario = None
        self._correo = None
        self._credenciales_mqtt = None

    # --- Registro ---

    def registrar(self, usuario: Usuario, contraseña: str) -> ResultadoRegistro:
        """Crea la cuenta en Supabase Auth.

        La fila de `usuarios` la crea el trigger de `auth.users` a partir de los
        metadatos: con la confirmación de correo activa no hay sesión tras el
        sign_up y RLS impediría insertarla desde la app.
        """
        correo = normalizar_correo(usuario.correo_institucional)
        metadatos = {
            "nombre": normalizar_nombre(usuario.nombre),
            "apellido_paterno": normalizar_nombre(usuario.apellido_paterno),
            "apellido_materno": normalizar_nombre(usuario.apellido_materno or "") or None,
            "medio_transporte": usuario.medio_transporte.value if usuario.medio_transporte else None,
        }
        # El trigger copia estos metadatos a `usuarios`: se validan antes de enviarlos.
        for campo in ("nombre", "apellido_paterno"):
            if not metadatos[campo]:
                raise DatosInvalidosError("Campo obligatorio", campo)
        for campo in ("nombre", "apellido_paterno", "apellido_materno"):
            error = validar_nombre_apellido_persona(metadatos[campo] or "")
            if error:
                raise DatosInvalidosError(error, campo)
        try:
            respuesta = self._cliente.auth.sign_up(
                {"email": correo, "password": contraseña, "options": {"data": metadatos}}
            )
        # AuthWeakPasswordError no hereda de AuthApiError: va antes que AuthError.
        except AuthWeakPasswordError as e:
            raise PasswordDebilError(e.reasons) from e
        except AuthApiError as e:
            if e.code in ("user_already_exists", "email_exists"):
                raise CorreoYaRegistradoError("Este correo ya está registrado") from e
            if e.code == "email_address_invalid":
                # El correo pasó el formato y la BD, pero Supabase no acepta enviarle
                # el correo de confirmación.
                raise DatosInvalidosError(
                    "No es posible enviar correos a esta dirección. "
                    "Revisa que esté bien escrita.",
                    "correo",
                ) from e
            if e.code == "validation_failed":
                # P. ej. "Unable to validate email address: invalid format".
                logger.warning("Supabase rechazó el registro por validación: %s", e.message)
                raise DatosInvalidosError(e.message) from e
            if e.code == "over_email_send_rate_limit" or e.status == 429:
                raise LimiteCorreosError(
                    "Se alcanzó el límite de correos de confirmación"
                ) from e
            raise _no_disponible(e) from e
        except (AuthError, httpx.HTTPError) as e:
            raise _no_disponible(e) from e

        if respuesta.user is None:
            raise ServicioNoDisponibleError("Supabase no devolvió el usuario creado")
        # Con la confirmación de correo activa, Supabase no revela duplicados:
        # devuelve un usuario falso sin identidades.
        if respuesta.user.identities == []:
            raise CorreoYaRegistradoError("Este correo ya está registrado")

        requiere_confirmacion = respuesta.session is None
        if not requiere_confirmacion:
            # Registro sin confirmación abre sesión: se cierra para que el
            # estudiante entre por el flujo normal de login.
            self._cerrar_sesion_remota()

        nuevo = Usuario(
            id_usuario=respuesta.user.id,
            nombre=metadatos["nombre"],
            apellido_paterno=metadatos["apellido_paterno"],
            apellido_materno=metadatos["apellido_materno"],
            correo_institucional=correo,
            medio_transporte=usuario.medio_transporte,
        )
        return ResultadoRegistro(usuario=nuevo, requiere_confirmacion=requiere_confirmacion)

    # --- Recuperar contraseña ---

    def solicitar_restablecimiento(self, correo: str) -> None:
        """Envía el correo con el código. Supabase responde igual exista o no la cuenta."""
        try:
            self._cliente.auth.reset_password_for_email(normalizar_correo(correo))
        except AuthApiError as e:
            if e.code == "over_email_send_rate_limit" or e.status == 429:
                raise LimiteCorreosError("Espera un momento antes de pedir otro código") from e
            raise _no_disponible(e) from e
        except (AuthError, httpx.HTTPError) as e:
            raise _no_disponible(e) from e

    def verificar_codigo_recuperacion(self, correo: str, codigo: str) -> None:
        """Canjea el código del correo de recuperación por una sesión temporal."""
        try:
            respuesta = self._cliente.auth.verify_otp(
                {"email": normalizar_correo(correo), "token": codigo.strip(), "type": "recovery"}
            )
        except AuthApiError as e:
            if e.code in ("otp_expired", "otp_disabled") or e.status in (400, 401, 403, 422):
                raise CodigoInvalidoError("El código es inválido o ya expiró") from e
            raise _no_disponible(e) from e
        except (AuthError, httpx.HTTPError) as e:
            raise _no_disponible(e) from e
        if respuesta.session is None:
            raise CodigoInvalidoError("El código es inválido o ya expiró")

    def confirmar_nueva_password(self, nueva: str) -> None:
        """Cambia la contraseña usando la sesión temporal de verificar_codigo_recuperacion."""
        # AuthWeakPasswordError y AuthSessionMissingError no heredan de AuthApiError:
        # van antes que AuthError para no confundirse con una falla de red.
        # Los errores de contraseña dejan la sesión abierta para reintentar.
        try:
            self._cliente.auth.update_user({"password": nueva})
        except AuthWeakPasswordError as e:
            raise PasswordDebilError(e.reasons) from e
        except AuthSessionMissingError as e:
            # La librería ya no tiene la sesión temporal de verificar_codigo_recuperacion.
            raise SinSesionError("La solicitud de recuperación expiró") from e
        except AuthApiError as e:
            if e.code == "same_password":
                raise PasswordRepetidaError("La nueva contraseña debe ser distinta") from e
            if e.code == "session_not_found" or e.status in (401, 403):
                raise SinSesionError("La solicitud de recuperación expiró") from e
            raise _no_disponible(e) from e
        except (AuthError, httpx.HTTPError) as e:
            raise _no_disponible(e) from e
        # La sesión de recuperación es de un solo uso: no se deja abierta.
        self._cerrar_sesion_remota()

    def cancelar_recuperacion(self) -> None:
        """Cierra la sesión temporal si el usuario abandona el flujo tras verificar el código."""
        self._cerrar_sesion_remota()

    # --- Internos ---

    def _registrar_sesion(self, sesion: Sesion) -> None:
        # Es bitácora: si falla, el usuario igual entra.
        try:
            self._cliente.table(TABLA_SESIONES).insert(sesion.to_row()).execute()
        except Exception:
            logger.exception("No se pudo registrar la sesión %s", sesion.id_sesion)

    def _cerrar_registro_sesion(self, sesion: Sesion) -> None:
        try:
            self._cliente.table(TABLA_SESIONES).update(
                {
                    "fecha_cierre_sesion": sesion.fecha_cierre_sesion.isoformat(),
                    "estado": sesion.estado.value,
                }
            ).eq("id_sesion", sesion.id_sesion).execute()
        except Exception:
            logger.exception("No se pudo cerrar el registro de la sesión %s", sesion.id_sesion)

    def _obtener_usuario(self, id_usuario: str) -> Usuario | None:
        try:
            resultado = (
                self._cliente.table(TABLA_USUARIOS)
                .select("*")
                .eq("id_usuario", id_usuario)
                .limit(1)
                .execute()
            )
        except Exception:
            logger.exception("No se pudo leer el perfil de %s", id_usuario)
            return None
        if not resultado.data:
            logger.warning("El usuario %s no tiene fila en la tabla usuario", id_usuario)
            return None
        return Usuario.from_row(resultado.data[0])

    def _cerrar_sesion_remota(self) -> None:
        try:
            self._cliente.auth.sign_out()
        except Exception:
            logger.warning("No se pudo cerrar la sesión en Supabase", exc_info=True)
