import asyncio
import logging

from parking_app.core.config import MAX_INTENTOS_LOGIN, SEGUNDOS_BLOQUEO_LOGIN
from parking_app.core.observable import Observable
from parking_app.core.validadores import validar_correo_institucional
from parking_app.services.auth_service import (
    AuthService,
    CorreoNoConfirmadoError,
    CredencialesInvalidasError,
    CuentaBloqueadaError,
    CuentaInactivaError,
    DatosInvalidosError,
    DemasiadasSolicitudesError,
    ServicioNoDisponibleError,
)
from parking_app.viewmodels.alerta import Alerta
from parking_app.viewmodels.navegacion import Navegar, llamar

logger = logging.getLogger(__name__)

_ORDINALES = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto", 5: "quinto"}

# Clase para integrar todas las operaciones/comandos a realizar, los estados de presentación y las propiedades derivadas.
class LoginViewModel(Observable):
    def __init__(
        self,
        auth_service: AuthService,
        al_iniciar_sesion: Navegar,
        al_ir_a_registro: Navegar,
        al_ir_a_recuperar: Navegar,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self._al_iniciar_sesion = al_iniciar_sesion
        self._al_ir_a_registro = al_ir_a_registro
        self._al_ir_a_recuperar = al_ir_a_recuperar

        self.correo = ""
        self.password = ""
        self.error_correo: str | None = None
        self.error_password: str | None = None
        self.cargando = False
        self.segundos_bloqueo = 0
        self._alerta_credenciales: Alerta | None = None
        self._alerta_general: Alerta | None = None
        self._cuenta_regresiva: asyncio.Task[None] | None = None

    # --- Propiedades de presentación ---

    @property
    def bloqueado(self) -> bool:
        return self.segundos_bloqueo > 0

    @property
    def puede_enviar(self) -> bool:
        return not self.cargando and not self.bloqueado

    @property
    def alerta(self) -> Alerta | None:
        if self.bloqueado:
            minutos, segundos = divmod(self.segundos_bloqueo, 60)
            return Alerta(
                titulo="Acceso bloqueado temporalmente",
                detalle=(
                    "Superaste el número de intentos permitidos. "
                    f"Podrás intentar de nuevo en {minutos}:{segundos:02d}."
                ),
            )
        return self._alerta_credenciales or self._alerta_general

    @property
    def resaltar_campos(self) -> bool:
        """Borde de advertencia en ambos campos (credenciales rechazadas o bloqueo)."""
        return self.bloqueado or self._alerta_credenciales is not None

    # --- Entradas desde la View ---

    def set_correo(self, valor: str) -> None:
        self.correo = valor
        self.error_correo = None
        self.notify_listeners()

    def set_password(self, valor: str) -> None:
        self.password = valor
        self.error_password = None
        self.notify_listeners()

    # --- Comandos ---

    async def iniciar_sesion(self) -> None:
        if not self.puede_enviar:
            return

        self.error_correo = validar_correo_institucional(self.correo)
        self.error_password = None if self.password else "Ingresa tu contraseña"
        if self.error_correo or self.error_password:
            self.notify_listeners()
            return

        self._alerta_credenciales = None
        self._alerta_general = None
        self.cargando = True
        self.notify_listeners()
        exito = False
        try:
            await asyncio.to_thread(self._auth.iniciar_sesion, self.correo, self.password)
            exito = True
        except CredencialesInvalidasError as e:
            self._alerta_credenciales = _alerta_credenciales(e.intentos_restantes)
        except CuentaBloqueadaError as e:
            self._iniciar_cuenta_regresiva(e.segundos_restantes)
        except CuentaInactivaError:
            self._alerta_general = Alerta(
                "Cuenta inactiva",
                "Tu cuenta está desactivada. Acude con el administrador del estacionamiento.",
            )
        except CorreoNoConfirmadoError:
            self._alerta_general = Alerta(
                "Correo sin confirmar",
                "Revisa tu bandeja institucional y confirma tu correo antes de iniciar sesión.",
            )
        except DatosInvalidosError:
            # El formato ya se valida aquí; si Supabase aun así lo rechaza, se avisa
            # sin contarlo como intento fallido.
            logger.warning("Supabase rechazó el formato de los datos de acceso", exc_info=True)
            self._alerta_general = Alerta(
                "Datos no válidos",
                "Revisa que tu correo y contraseña estén bien escritos e intenta de nuevo.",
            )
        except DemasiadasSolicitudesError:
            # Límite de Supabase (429), distinto del bloqueo propio de 3 intentos.
            self._alerta_general = Alerta(
                "Demasiados intentos",
                "Espera un momento antes de volver a intentarlo.",
            )
        except ServicioNoDisponibleError:
            logger.exception("Fallo de conexión al iniciar sesión")
            self._alerta_general = Alerta(
                "No se pudo conectar",
                "Revisa tu conexión a internet e intenta de nuevo.",
            )
        finally:
            self.cargando = False

        if exito:
            self.password = ""
        self.notify_listeners()
        if exito:
            await llamar(self._al_iniciar_sesion)

    async def ir_a_registro(self) -> None:
        await llamar(self._al_ir_a_registro)

    async def ir_a_recuperar(self) -> None:
        await llamar(self._al_ir_a_recuperar)

    def liberar(self) -> None:
        """Detiene tareas en curso al salir de la pantalla."""
        if self._cuenta_regresiva is not None:
            self._cuenta_regresiva.cancel()
            self._cuenta_regresiva = None

    # --- Internos ---

    def _iniciar_cuenta_regresiva(self, segundos: int) -> None:
        self.segundos_bloqueo = segundos
        self.liberar()
        self._cuenta_regresiva = asyncio.create_task(self._contar(self.correo))

    async def _contar(self, correo_bloqueado: str) -> None:
        while self.segundos_bloqueo > 0:
            await asyncio.sleep(1)
            self.segundos_bloqueo = self._auth.segundos_bloqueo_restantes(correo_bloqueado)
            self.notify_listeners()


def _alerta_credenciales(intentos_restantes: int) -> Alerta:
    intentos = "Te queda 1 intento" if intentos_restantes == 1 else (
        f"Te quedan {intentos_restantes} intentos"
    )
    ordinal = _ORDINALES.get(MAX_INTENTOS_LOGIN, f"{MAX_INTENTOS_LOGIN}.º")
    minutos = SEGUNDOS_BLOQUEO_LOGIN // 60
    return Alerta(
        titulo="Correo o contraseña incorrectos",
        detalle=(
            f"{intentos}. Después del {ordinal} intento fallido, "
            f"el acceso se bloqueará durante {minutos} minutos."
        ),
    )
