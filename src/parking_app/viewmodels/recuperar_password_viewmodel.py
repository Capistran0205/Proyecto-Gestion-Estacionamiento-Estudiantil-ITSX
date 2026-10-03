import asyncio
import logging
import time
from collections.abc import Callable
from enum import IntEnum

from parking_app.core.config import VIGENCIA_CODIGO_SEGUNDOS
from parking_app.core.observable import Observable
from parking_app.core.validadores import (
    estado_requisitos_password,
    normalizar_correo,
    validar_correo_institucional,
)
from parking_app.services.auth_service import (
    AuthService,
    CodigoInvalidoError,
    LimiteCorreosError,
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

TOTAL_PASOS = 3

ALERTA_SIN_CONEXION = Alerta(
    "No se pudo conectar", "Revisa tu conexión a internet e intenta de nuevo."
)
ALERTA_LIMITE = Alerta(
    "Espera un momento",
    "Ya solicitaste un código hace poco. Intenta de nuevo en un minuto.",
)


class Paso(IntEnum):
    CORREO = 1
    CODIGO = 2
    NUEVA_PASSWORD = 3
    COMPLETADO = 4


class RecuperarPasswordViewModel(Observable):
    def __init__(
        self,
        auth_service: AuthService,
        emqx_service: EmqxAdminService,
        al_ir_a_login: Navegar,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self._emqx = emqx_service
        self._al_ir_a_login = al_ir_a_login
        self._reloj = reloj

        self.paso = Paso.CORREO
        self.correo = ""
        self.codigo = ""
        self.password = ""
        self.confirmar_password = ""

        self.error_correo: str | None = None
        self.error_codigo: str | None = None
        self.codigo_invalido = False
        self.error_password: str | None = None
        self.error_confirmar: str | None = None
        self.alerta: Alerta | None = None
        self.cargando = False

        self._vence_en: float | None = None
        self._temporizador: asyncio.Task[None] | None = None
        self._codigo_verificado = False
        self._validar_password_en_vivo = False

    # --- Propiedades de presentación ---

    @property
    def numero_paso(self) -> int:
        return min(int(self.paso), TOTAL_PASOS)

    @property
    def total_pasos(self) -> int:
        return TOTAL_PASOS

    @property
    def correo_normalizado(self) -> str:
        return normalizar_correo(self.correo)

    @property
    def segundos_restantes(self) -> int:
        if self._vence_en is None:
            return 0
        return max(0, int(self._vence_en - self._reloj() + 0.999))

    @property
    def texto_vencimiento(self) -> str:
        minutos, segundos = divmod(self.segundos_restantes, 60)
        return f"{minutos:02d}:{segundos:02d}"

    @property
    def codigo_vencido(self) -> bool:
        return self._vence_en is not None and self.segundos_restantes == 0

    @property
    def mostrar_error_codigo(self) -> bool:
        """Estado del mockup: aviso bajo el campo y botón "Enviar un código nuevo"."""
        return self.codigo_invalido or self.codigo_vencido

    @property
    def requisitos_password(self) -> list[tuple[str, bool]]:
        estado = estado_requisitos_password(self.password)
        return [(texto, estado[clave]) for clave, texto in TEXTOS_REQUISITOS.items()]

    @property
    def puede_enviar(self) -> bool:
        return not self.cargando

    # --- Entradas desde la View ---

    def set_correo(self, valor: str) -> None:
        self.correo = valor
        self.error_correo = None
        self.notify_listeners()

    def set_codigo(self, valor: str) -> None:
        self.codigo = "".join(c for c in valor if c.isdigit())
        self.error_codigo = None
        self.codigo_invalido = False
        self.notify_listeners()

    def set_password(self, valor: str) -> None:
        self.password = valor
        self._revalidar_password()
        self.notify_listeners()

    def set_confirmar_password(self, valor: str) -> None:
        self.confirmar_password = valor
        self._revalidar_password()
        self.notify_listeners()

    # --- Comandos ---

    async def enviar_codigo(self) -> None:
        if not self.puede_enviar:
            return
        self.alerta = None
        self.error_correo = validar_correo_institucional(self.correo)
        if self.error_correo:
            self.notify_listeners()
            return
        if await self._solicitar_codigo():
            self.paso = Paso.CODIGO
        self.notify_listeners()

    async def reenviar_codigo(self) -> None:
        if not self.puede_enviar:
            return
        self.alerta = None
        if await self._solicitar_codigo():
            self.codigo = ""
            self.codigo_invalido = False
            self.error_codigo = None
        self.notify_listeners()

    async def verificar_codigo(self) -> None:
        if not self.puede_enviar:
            return
        self.alerta = None
        if not self.codigo:
            self.error_codigo = "Escribe el código de verificación"
            self.notify_listeners()
            return

        self.cargando = True
        self.notify_listeners()
        try:
            await asyncio.to_thread(
                self._auth.verificar_codigo_recuperacion, self.correo_normalizado, self.codigo
            )
        except CodigoInvalidoError:
            self.codigo_invalido = True
        except ServicioNoDisponibleError:
            logger.exception("Fallo al verificar el código de recuperación")
            self.alerta = ALERTA_SIN_CONEXION
        else:
            self._codigo_verificado = True
            self._detener_temporizador()
            self.paso = Paso.NUEVA_PASSWORD
        finally:
            self.cargando = False
        self.notify_listeners()

    async def guardar_password(self) -> None:
        if not self.puede_enviar:
            return
        self.alerta = None
        self._validar_password_en_vivo = True
        self._revalidar_password()
        if self.error_password or self.error_confirmar:
            self.notify_listeners()
            return

        self.cargando = True
        self.notify_listeners()
        try:
            await asyncio.to_thread(self._auth.confirmar_nueva_password, self.password)
        except PasswordRepetidaError:
            self.error_password = "Elige una contraseña distinta a la anterior"
        except PasswordDebilError as e:
            self.error_password = mensaje_password_debil(e.razones)
        except SinSesionError:
            self._reiniciar(Alerta(
                "La verificación expiró",
                "Pasó demasiado tiempo desde que verificaste el código. Solicita uno nuevo.",
            ))
        except ServicioNoDisponibleError:
            logger.exception("Fallo al guardar la nueva contraseña")
            self.alerta = ALERTA_SIN_CONEXION
        else:
            self._codigo_verificado = False
            await self._sincronizar_mqtt()
            self.password = ""
            self.confirmar_password = ""
            self.paso = Paso.COMPLETADO
        finally:
            self.cargando = False
        self.notify_listeners()

    async def regresar(self) -> None:
        if self.paso in (Paso.CORREO, Paso.COMPLETADO):
            await self.ir_a_login()
            return
        if self.paso == Paso.NUEVA_PASSWORD:
            await asyncio.to_thread(self._auth.cancelar_recuperacion)
        self._reiniciar()
        self.notify_listeners()

    async def ir_a_login(self) -> None:
        await llamar(self._al_ir_a_login)

    def liberar(self) -> None:
        """Al salir de la pantalla: detiene el temporizador y cierra la sesión temporal."""
        self._detener_temporizador()
        if self._codigo_verificado:
            self._codigo_verificado = False
            try:
                asyncio.get_running_loop().create_task(
                    asyncio.to_thread(self._auth.cancelar_recuperacion)
                )
            except RuntimeError:
                self._auth.cancelar_recuperacion()

    # --- Internos ---

    async def _solicitar_codigo(self) -> bool:
        self.cargando = True
        self.notify_listeners()
        try:
            await asyncio.to_thread(self._auth.solicitar_restablecimiento, self.correo_normalizado)
        except LimiteCorreosError:
            self.alerta = ALERTA_LIMITE
            return False
        except ServicioNoDisponibleError:
            logger.exception("Fallo al solicitar el código de recuperación")
            self.alerta = ALERTA_SIN_CONEXION
            return False
        finally:
            self.cargando = False
        self._iniciar_temporizador()
        return True

    async def _sincronizar_mqtt(self) -> None:
        # La cuenta MQTT usa la misma contraseña: si no se actualiza, la vista de
        # ocupación no podría conectarse al broker. Igual que en el registro, un
        # fallo aquí se registra sin bloquear el cambio ya hecho en Supabase.
        try:
            await asyncio.to_thread(
                self._emqx.crear_credencial, self.correo_normalizado, self.password
            )
        except Exception:
            logger.exception("No se pudo actualizar la credencial MQTT de %s", self.correo_normalizado)

    def _revalidar_password(self) -> None:
        if not self._validar_password_en_vivo:
            return
        if not self.password:
            self.error_password = "Escribe una contraseña"
        elif not all(estado_requisitos_password(self.password).values()):
            self.error_password = "Tu contraseña no cumple los requisitos"
        else:
            self.error_password = None

        if not self.confirmar_password:
            self.error_confirmar = "Confirma tu contraseña"
        elif self.confirmar_password != self.password:
            self.error_confirmar = "Las contraseñas no coinciden"
        else:
            self.error_confirmar = None

    def _reiniciar(self, alerta: Alerta | None = None) -> None:
        self._detener_temporizador()
        self._codigo_verificado = False
        self._vence_en = None
        self._validar_password_en_vivo = False
        self.paso = Paso.CORREO
        self.codigo = ""
        self.password = ""
        self.confirmar_password = ""
        self.codigo_invalido = False
        self.error_codigo = self.error_password = self.error_confirmar = None
        self.alerta = alerta

    def _iniciar_temporizador(self) -> None:
        self._detener_temporizador()
        self._vence_en = self._reloj() + VIGENCIA_CODIGO_SEGUNDOS
        try:
            self._temporizador = asyncio.get_running_loop().create_task(self._contar())
        except RuntimeError:
            self._temporizador = None

    def _detener_temporizador(self) -> None:
        if self._temporizador is not None:
            self._temporizador.cancel()
            self._temporizador = None

    async def _contar(self) -> None:
        while self.segundos_restantes > 0:
            await asyncio.sleep(1)
            self.notify_listeners()
