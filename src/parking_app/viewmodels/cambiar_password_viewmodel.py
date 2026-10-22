import asyncio
import logging

from parking_app.core.observable import Observable
from parking_app.core.validadores import estado_requisitos_password
from parking_app.services.auth_service import (
    AuthService,
    CambioPasswordRevertidoError,
    CuentaBloqueadaError,
    DemasiadasSolicitudesError,
    PasswordActualIncorrectaError,
    PasswordDebilError,
    PasswordRepetidaError,
    ServicioNoDisponibleError,
    SinSesionError,
)
from parking_app.services.emqx_admin_service import EmqxAdminService
from parking_app.viewmodels.alerta import Alerta, mensaje_password_debil
from parking_app.viewmodels.navegacion import Navegar, llamar
from parking_app.viewmodels.registro_viewmodel import TEXTOS_REQUISITOS

logger = logging.getLogger(__name__)

ERROR_ACTUAL_INCORRECTA = "La contraseña actual no es correcta"
ALERTA_ACTUAL_INCORRECTA = Alerta(
    "No se pudo cambiar la contraseña",
    "La contraseña actual no es correcta. Inténtalo de nuevo.",
)
ALERTA_SIN_CONEXION = Alerta(
    "No se pudo cambiar la contraseña",
    "Revisa tu conexión a internet e intenta de nuevo.",
)
ALERTA_REVERTIDO = Alerta(
    "No se pudo cambiar la contraseña",
    "Hubo un problema con el servidor de sensores y tu contraseña no cambió. "
    "Intenta de nuevo en unos minutos.",
)


def _texto_espera(segundos: int) -> str:
    minutos = max(1, (segundos + 59) // 60)
    return f"{minutos} minuto" if minutos == 1 else f"{minutos} minutos"


# Clase representativa de "Cambiar contraseña" con sesión iniciada (RF-04, RF-05).
# El aviso por correo (RF-06) lo envía Supabase Auth: la app no lo implementa.
class CambiarPasswordViewModel(Observable):
    def __init__(
        self,
        auth_service: AuthService,
        emqx_service: EmqxAdminService,
        al_regresar: Navegar,
        al_cambiar: Navegar | None = None,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self._emqx = emqx_service
        self._al_regresar = al_regresar
        self._al_cambiar = al_cambiar

        self.actual = ""
        self.nueva = ""
        self.confirmar = ""
        self.error_actual: str | None = None
        self.error_nueva: str | None = None
        self.error_confirmar: str | None = None
        self.alerta: Alerta | None = None
        self.cargando = False
        self.completado = False
        self._validar_en_vivo = False
        # Rechazos del servidor por campo ("actual", "nueva"): duran hasta editar ese campo.
        self._errores_servidor: dict[str, str] = {}

    # --- Propiedades de presentación ---

    @property
    def correo(self) -> str:
        usuario = self._auth.usuario_actual
        return usuario.correo_institucional if usuario else (self._auth.correo_actual or "")

    @property
    def requisitos_password(self) -> list[tuple[str, bool]]:
        estado = estado_requisitos_password(self.nueva)
        return [(texto, estado[clave]) for clave, texto in TEXTOS_REQUISITOS.items()]

    @property
    def puede_enviar(self) -> bool:
        return not self.cargando

    # --- Entradas desde la View ---

    def set_actual(self, valor: str) -> None:
        self.actual = valor
        self._cambio("actual")

    def set_nueva(self, valor: str) -> None:
        self.nueva = valor
        self._cambio("nueva")

    def set_confirmar(self, valor: str) -> None:
        self.confirmar = valor
        self._cambio("confirmar")

    # --- Comandos ---

    async def actualizar(self) -> None:
        if not self.puede_enviar:
            return
        self.alerta = None
        self._errores_servidor.clear()
        self._validar_en_vivo = True
        self._validar()
        if self.error_actual or self.error_nueva or self.error_confirmar:
            self.notify_listeners()
            return

        self.cargando = True
        self.notify_listeners()
        try:
            await asyncio.to_thread(
                self._auth.cambiar_password, self.actual, self.nueva, self._emqx.crear_credencial
            )
        except PasswordActualIncorrectaError:
            self._errores_servidor["actual"] = ERROR_ACTUAL_INCORRECTA
            self.alerta = ALERTA_ACTUAL_INCORRECTA
        except CuentaBloqueadaError as e:
            self._errores_servidor["actual"] = ERROR_ACTUAL_INCORRECTA
            self.alerta = Alerta(
                "Demasiados intentos",
                f"Espera {_texto_espera(e.segundos_restantes)} antes de intentarlo de nuevo.",
            )
        except PasswordRepetidaError:
            self._errores_servidor["nueva"] = "Elige una contraseña distinta a la actual"
        except PasswordDebilError as e:
            self._errores_servidor["nueva"] = mensaje_password_debil(e.razones)
        except CambioPasswordRevertidoError:
            self.alerta = ALERTA_REVERTIDO
        except SinSesionError:
            self.alerta = Alerta(
                "Tu sesión expiró", "Cierra sesión y vuelve a entrar para cambiar tu contraseña."
            )
        except DemasiadasSolicitudesError:
            self.alerta = Alerta(
                "Demasiados intentos", "Espera un momento antes de volver a intentarlo."
            )
        except ServicioNoDisponibleError:
            logger.exception("Fallo al cambiar la contraseña")
            self.alerta = ALERTA_SIN_CONEXION
        else:
            # Las contraseñas no se quedan en el ViewModel más de lo necesario.
            self.actual = self.nueva = self.confirmar = ""
            self.completado = True
            if self._al_cambiar is not None:
                await llamar(self._al_cambiar)
        finally:
            self.cargando = False
        self._validar()
        self.notify_listeners()

    async def regresar(self) -> None:
        await llamar(self._al_regresar)

    # --- Internos ---

    def _cambio(self, campo: str) -> None:
        self._errores_servidor.pop(campo, None)
        self.alerta = None
        if self._validar_en_vivo:
            self._validar()
        else:
            setattr(self, f"error_{campo}", None)
        self.notify_listeners()

    def _validar(self) -> None:
        if self.completado:
            self.error_actual = self.error_nueva = self.error_confirmar = None
            return

        if not self.actual:
            error_actual = "Escribe tu contraseña actual"
        else:
            error_actual = None

        if not self.nueva:
            error_nueva = "Escribe una contraseña nueva"
        elif not all(estado_requisitos_password(self.nueva).values()):
            error_nueva = "Tu contraseña no cumple los requisitos"
        elif self.nueva == self.actual:
            error_nueva = "La nueva contraseña debe ser distinta a la actual"
        else:
            error_nueva = None

        if not self.confirmar:
            self.error_confirmar = "Confirma tu nueva contraseña"
        elif self.confirmar != self.nueva:
            self.error_confirmar = "Las contraseñas no coinciden"
        else:
            self.error_confirmar = None

        # Un error local tiene prioridad: es lo primero que hay que corregir.
        self.error_actual = error_actual or self._errores_servidor.get("actual")
        self.error_nueva = error_nueva or self._errores_servidor.get("nueva")
