import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from parking_app.core.observable import Observable
from parking_app.models.reserva_cajon import EstadoReserva, ReservaCajon
from parking_app.models.usuario import Rol
from parking_app.services.almacen_reserva import AlmacenReserva
from parking_app.services.auth_service import AuthService
from parking_app.services.reservas_service import (
    ReservaError,
    ReservasNoDisponiblesError,
    ReservasService,
)
from parking_app.viewmodels.aviso_cambios import AvisoDeCambios
from parking_app.viewmodels.formato import hora_local
from parking_app.viewmodels.navegacion import Navegar, llamar
from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TarjetaReserva:
    """Tarjeta "Mi reserva" del menú: subtítulo y si lleva la insignia "En uso"."""

    subtitulo: str
    en_uso: bool

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
        al_ir_a_perfil: Navegar | None = None,
        al_ir_a_reservas: Navegar | None = None,
        reservas_service: ReservasService | None = None,
        almacen: AlmacenReserva | None = None,
        al_ir_a_mi_reserva: Navegar | None = None,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self.ocupacion = ocupacion
        self._al_ir_a_ocupacion = al_ir_a_ocupacion
        self._al_cerrar_sesion = al_cerrar_sesion
        self._al_ir_a_perfil = al_ir_a_perfil
        self._al_ir_a_reservas = al_ir_a_reservas
        self._al_ir_a_mi_reserva = al_ir_a_mi_reserva
        self._ahora = ahora
        self._reservas = reservas_service
        self._almacen = almacen
        self.cerrando_sesion = False
        # Reserva vigente del estudiante (tarjeta "Mi reserva"); None si no tiene.
        self.reserva: ReservaCajon | None = None
        self._consultando = False
        # Solo se consulta al cambiar el cajón de su reserva (sin reserva no hay nada que seguir).
        self._aviso = AvisoDeCambios(ocupacion, self._cambio_en_cajon,
                                     lambda: self.reserva.etiqueta_cajon if self.reserva else None)

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
        return usuario.iniciales

    @property
    def es_administrador(self) -> bool:
        """Solo el administrador ve el módulo de reservas (Módulo C)."""
        usuario = self._auth.usuario_actual
        return usuario is not None and usuario.rol == Rol.ADMINISTRADOR

    @property
    def tarjeta_reserva(self) -> TarjetaReserva | None:
        """Solo con una reserva vigente: antes de la llegada lleva al QR; en uso, al tiempo."""
        r = self.reserva
        if r is None or self.es_administrador:
            return None
        if r.estado == EstadoReserva.EN_USO:
            return TarjetaReserva(
                f"Cajón {r.etiqueta_cajon} · termina a las {hora_local(r.fecha_fin)}", True)
        return TarjetaReserva("Código QR y tiempo de tu reserva", False)

    # --- Reserva vigente ---

    async def iniciar(self) -> None:
        await self.actualizar_reserva()
        self._aviso.escuchar()

    def liberar(self) -> None:
        self._aviso.dejar()

    async def actualizar_reserva(self) -> None:
        """Copia local primero (también sin internet) y luego el servidor."""
        usuario = self._auth.usuario_actual
        if (usuario is None or self.es_administrador or self._reservas is None
                or self._consultando):
            return
        self._consultando = True
        try:
            local = self._almacen.leer(usuario.id_usuario) if self._almacen else None
            if self.reserva is None and local is not None and local.estado.vigente:
                self.reserva = local
                self.notify_listeners()
            try:
                servidor = await asyncio.to_thread(
                    self._reservas.reserva_vigente, usuario.id_usuario)
            except (ReservaError, ReservasNoDisponiblesError) as e:
                # Sin servidor se conserva lo que se mostraba (o la copia local).
                logger.warning("No se pudo consultar la reserva vigente: %s", e)
                return
            if servidor is None and local is not None and self._almacen is not None:
                # Terminó mientras tanto (expiró, salida del RF-14...): la copia ya no sirve.
                self._almacen.borrar()
            self.reserva = servidor
        finally:
            self._consultando = False
        self.notify_listeners()

    async def _cambio_en_cajon(self) -> None:
        if self.reserva is not None:
            await self.actualizar_reserva()

    # --- Comandos ---

    async def ir_a_mi_reserva(self) -> None:
        if self._al_ir_a_mi_reserva is not None:
            await llamar(self._al_ir_a_mi_reserva)


    async def ir_a_reservas(self) -> None:
        if self.es_administrador and self._al_ir_a_reservas is not None:
            await llamar(self._al_ir_a_reservas)

    async def ir_a_ocupacion(self) -> None:
        await llamar(self._al_ir_a_ocupacion)

    async def ir_a_perfil(self) -> None:
        if self._al_ir_a_perfil is not None:
            await llamar(self._al_ir_a_perfil)

    def refrescar(self) -> None:
        """Vuelve a pintar el saludo y el menú (p. ej. tras editar el perfil)."""
        self.notify_listeners()

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
