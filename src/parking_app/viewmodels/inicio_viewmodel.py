import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from parking_app.core.observable import Observable
from parking_app.services.auth_service import AuthService
from parking_app.viewmodels.navegacion import Navegar, llamar
from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel

logger = logging.getLogger(__name__)

# Esta clase implementa el observable
class InicioViewModel(Observable):
    """Menú principal: saludo, resumen en vivo del estacionamiento y menú de usuario.

    El estado de ocupación lo aporta el OcupacionViewModel de la sesión (el
    mismo que usa la pantalla de mapa): una sola conexión MQTT para ambas.
    """

    def __init__(
        self,
        auth_service: AuthService,
        ocupacion: OcupacionViewModel,
        al_ir_a_ocupacion: Navegar,
        al_cerrar_sesion: Navegar,
        ahora: Callable[[], datetime] = datetime.now,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self.ocupacion = ocupacion
        self._al_ir_a_ocupacion = al_ir_a_ocupacion
        self._al_cerrar_sesion = al_cerrar_sesion
        self._ahora = ahora
        self.cerrando_sesion = False

    # --- Datos del estudiante ---

    @property
    def saludo(self) -> str:
        hora = self._ahora().hour
        if 5 <= hora < 12:
            return "Buenos días"
        if 12 <= hora < 19:
            return "Buenas tardes"
        return "Buenas noches"

    @property
    def correo(self) -> str:
        usuario = self._auth.usuario_actual
        if usuario is not None:
            return usuario.correo_institucional
        # La contraseña MQTT se descarta al conectar: el correo se lee aparte.
        return self._auth.correo_actual or ""

    @property
    def nombre_corto(self) -> str:
        """Nombre + apellido paterno para el saludo."""
        usuario = self._auth.usuario_actual
        if usuario is None:
            return "Estudiante"
        return " ".join(p for p in (usuario.nombre, usuario.apellido_paterno) if p)

    @property
    def nombre_completo(self) -> str:
        usuario = self._auth.usuario_actual
        return usuario.nombre_completo if usuario else "Estudiante"

    @property
    def numero_control(self) -> str:
        # La BD no guarda el número de control: el correo institucional lo
        # lleva como parte local (p. ej. 237O00526@itsx.edu.mx).
        return self.correo.split("@", 1)[0].upper() if self.correo else ""

    @property
    def iniciales(self) -> str:
        usuario = self._auth.usuario_actual
        if usuario is None:
            return (self.correo[:1] or "?").upper()
        partes = [p for p in (usuario.nombre, usuario.apellido_paterno) if p]
        return "".join(p[0] for p in partes).upper()[:2] or "?"

    # --- Comandos ---

    async def ir_a_ocupacion(self) -> None:
        await llamar(self._al_ir_a_ocupacion)

    async def cerrar_sesion(self) -> None:
        if self.cerrando_sesion:
            return
        self.cerrando_sesion = True
        self.notify_listeners()
        try:
            await asyncio.to_thread(self._auth.cerrar_sesion)
        except Exception:
            # El cierre local (credenciales en memoria) ya ocurrió dentro del
            # servicio; un fallo remoto no debe dejar al usuario atrapado.
            logger.exception("Fallo al cerrar sesión en el servidor")
        finally:
            self.cerrando_sesion = False
        await llamar(self._al_cerrar_sesion)
