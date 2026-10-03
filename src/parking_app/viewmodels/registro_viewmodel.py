import asyncio
import logging

from parking_app.core.observable import Observable
from parking_app.core.validadores import (
    estado_requisitos_password,
    normalizar_correo,
    normalizar_nombre,
    validar_correo_institucional,
    validar_nombre_apellido_persona,
)
from parking_app.models.usuario import MedioTransporte, Usuario
from parking_app.services.auth_service import (
    AuthService,
    CorreoYaRegistradoError,
    DatosInvalidosError,
    LimiteCorreosError,
    PasswordDebilError,
    ResultadoRegistro,
    ServicioNoDisponibleError,
)
from parking_app.services.emqx_admin_service import EmqxAdminService
from parking_app.viewmodels.alerta import Alerta, mensaje_password_debil
from parking_app.viewmodels.navegacion import Navegar, llamar

logger = logging.getLogger(__name__)

CAMPO_OBLIGATORIO = "Campo obligatorio"

TEXTOS_REQUISITOS = {
    "longitud" : "Al menos 8 caracteres",
    "mayuscula": "Al menos una letra mayúscula",
    "minuscula": "Al menos una letra minúscula",
    "numero": "Al menos un número",
    "especial": "Al menos un carácter especial (por ejemplo ! # $ %)",
}

# Clase representativa para guardar los campos del formulario, 
# propiedades como las alertas de errores, requisitos para la contraseña
# las 
class RegistroViewModel(Observable):
    def __init__(
        self,
        auth_service: AuthService,
        emqx_service: EmqxAdminService,
        al_ir_a_login: Navegar,
        al_ir_a_recuperar: Navegar,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self._emqx = emqx_service
        self._al_ir_a_login = al_ir_a_login
        self._al_ir_a_recuperar = al_ir_a_recuperar

        self.nombre = ""
        self.apellido_paterno = ""
        self.apellido_materno = ""
        self.medio_transporte: MedioTransporte | None = None
        self.correo = ""
        self.password = ""
        self.confirmar_password = ""

        self.errores: dict[str, str | None] = {}
        self.correo_duplicado = False
        self.cargando = False
        self.resultado: ResultadoRegistro | None = None
        self._faltantes = 0
        self._alerta_general: Alerta | None = None
        # Rechazos de Supabase por campo (contraseña débil, correo inválido…):
        # cada uno se mantiene hasta que se edita ese campo.
        self._errores_servidor: dict[str, str] = {}
        # Tras el primer intento de envío, los errores se recalculan al escribir.
        self._validar_en_vivo = False

    # --- Propiedades de presentación ---

    def error(self, campo: str) -> str | None:
        return self.errores.get(campo)

    @property
    def alerta(self) -> Alerta | None:
        if self._alerta_general is not None:
            return self._alerta_general
        if self._faltantes:
            titulo = (
                "Falta 1 campo por completar"
                if self._faltantes == 1
                else f"Faltan {self._faltantes} campos por completar"
            )
            return Alerta(titulo, "Revisa los campos marcados para poder crear tu cuenta.")
        if any(self.errores.values()):
            return Alerta(
                "Revisa los campos marcados",
                "Hay datos que no cumplen con lo solicitado.",
            )
        return None

    @property
    def requisitos_password(self) -> list[tuple[str, bool]]:
        estado = estado_requisitos_password(self.password)
        return [(texto, estado[clave]) for clave, texto in TEXTOS_REQUISITOS.items()]

    @property
    def puede_enviar(self) -> bool:
        return not self.cargando

    @property
    def registro_completado(self) -> bool:
        return self.resultado is not None

    @property
    def titulo_exito(self) -> str:
        return "¡Cuenta creada!"

    @property
    def detalle_exito(self) -> str:
        if self.resultado and self.resultado.requiere_confirmacion:
            return (
                f"Te enviamos un correo a {self.resultado.usuario.correo_institucional}. "
                "Confirma tu cuenta desde el enlace y después inicia sesión."
            )
        return "Tu registro se completó. Ya puedes iniciar sesión con tu correo institucional."

    # --- Entradas desde la View ---

    def set_nombre(self, valor: str) -> None:
        self.nombre = valor
        self._cambio("nombre")

    def set_apellido_paterno(self, valor: str) -> None:
        self.apellido_paterno = valor
        self._cambio("apellido_paterno")

    def set_apellido_materno(self, valor: str) -> None:
        self.apellido_materno = valor
        self._cambio("apellido_materno")

    def set_medio_transporte(self, valor: MedioTransporte) -> None:
        self.medio_transporte = valor
        self._cambio("medio_transporte")

    def set_correo(self, valor: str) -> None:
        self.correo = valor
        self.correo_duplicado = False
        self._cambio("correo")

    def set_password(self, valor: str) -> None:
        self.password = valor
        self._cambio("password")

    def set_confirmar_password(self, valor: str) -> None:
        self.confirmar_password = valor
        self._cambio("confirmar_password")

    # --- Comandos ---

    async def crear_cuenta(self) -> None:
        if not self.puede_enviar:
            return

        self._alerta_general = None
        self._validar_en_vivo = True
        self._validar()
        if self.alerta is not None:
            self.notify_listeners()
            return

        self.cargando = True
        self.notify_listeners()
        usuario = Usuario(
            id_usuario="",
            nombre=normalizar_nombre(self.nombre),
            apellido_paterno=normalizar_nombre(self.apellido_paterno),
            apellido_materno=normalizar_nombre(self.apellido_materno),
            correo_institucional=normalizar_correo(self.correo),
            medio_transporte=self.medio_transporte,
        )
        try:
            resultado = await asyncio.to_thread(self._auth.registrar, usuario, self.password)
        except CorreoYaRegistradoError:
            self.correo_duplicado = True
        except PasswordDebilError as e:
            # Cumple las reglas locales, pero no la política de Supabase.
            self._errores_servidor["password"] = mensaje_password_debil(e.razones)
            self._validar()
        except DatosInvalidosError as e:
            if e.campo is not None:
                # Se marca el campo; la alerta "Revisa los campos marcados" sale sola.
                self._errores_servidor[e.campo] = str(e)
                self._validar()
            else:
                # Supabase no dijo qué campo: no hay nada que marcar.
                logger.warning("El servicio rechazó los datos del registro: %s", e)
                self._alerta_general = Alerta(
                    "No se pudieron validar tus datos",
                    "Revisa que estén bien escritos e intenta de nuevo.",
                )
        except LimiteCorreosError:
            self._alerta_general = Alerta(
                "Demasiados registros por ahora",
                "Se alcanzó el límite de correos de confirmación. Intenta de nuevo en unos minutos.",
            )
        except ServicioNoDisponibleError:
            logger.exception("Fallo al registrar la cuenta")
            self._alerta_general = Alerta(
                "No se pudo crear tu cuenta",
                "Revisa tu conexión a internet e intenta de nuevo.",
            )
        else:
            await self._aprovisionar_mqtt(resultado.usuario.correo_institucional)
            self.resultado = resultado
            self.password = ""
            self.confirmar_password = ""
        finally:
            self.cargando = False
        self.notify_listeners()

    async def ir_a_login(self) -> None:
        await llamar(self._al_ir_a_login)

    async def ir_a_recuperar(self) -> None:
        await llamar(self._al_ir_a_recuperar)

    # --- Internos ---

    async def _aprovisionar_mqtt(self, correo: str) -> None:
        # Decisión vigente (CLAUDE.MD): si EMQX falla tras un registro exitoso en
        # Supabase, se registra el error y el alta continúa.
        try:
            await asyncio.to_thread(self._emqx.crear_credencial, correo, self.password)
        except Exception:
            logger.exception("No se pudo aprovisionar la credencial MQTT de %s", correo)

    def _cambio(self, campo: str) -> None:
        self._errores_servidor.pop(campo, None)
        if self._validar_en_vivo:
            self._validar()
        self.notify_listeners()

    def _validar(self) -> None:
        vacios = {
            "nombre": not self.nombre.strip(),
            "apellido_paterno": not self.apellido_paterno.strip(),
            "medio_transporte": self.medio_transporte is None,
            "correo": not self.correo.strip(),
            "password": not self.password,
            "confirmar_password": not self.confirmar_password,
        }
        self._faltantes = sum(vacios.values())

        errores: dict[str, str | None] = {
            "nombre": (
                CAMPO_OBLIGATORIO if vacios["nombre"] else validar_nombre_apellido_persona(self.nombre)
            ),
            "apellido_paterno": (
                CAMPO_OBLIGATORIO
                if vacios["apellido_paterno"]
                else validar_nombre_apellido_persona(self.apellido_paterno)
            ),
            # Opcional: solo se valida el formato si se escribió algo.
            "apellido_materno": validar_nombre_apellido_persona(self.apellido_materno),
            "medio_transporte": (
                "Selecciona tu medio de transporte" if vacios["medio_transporte"] else None
            ),
            "correo": (
                CAMPO_OBLIGATORIO if vacios["correo"] else validar_correo_institucional(self.correo)
            ),
        }
        if vacios["password"]:
            errores["password"] = "Escribe una contraseña"
        elif not all(estado_requisitos_password(self.password).values()):
            errores["password"] = "Tu contraseña no cumple los requisitos"
        else:
            errores["password"] = None

        if vacios["confirmar_password"]:
            errores["confirmar_password"] = "Confirma tu contraseña"
        elif self.confirmar_password != self.password:
            errores["confirmar_password"] = "Las contraseñas no coinciden"
        else:
            errores["confirmar_password"] = None

        # Un error local tiene prioridad: es lo que el usuario debe corregir primero.
        for campo, mensaje in self._errores_servidor.items():
            if errores.get(campo) is None:
                errores[campo] = mensaje

        self.errores = errores
