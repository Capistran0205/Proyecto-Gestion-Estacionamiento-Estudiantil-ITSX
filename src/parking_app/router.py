"""Navegación entre pantallas y guardia de sesión."""

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

import flet as ft

from parking_app.models.usuario import Rol
from parking_app.services.almacen_reserva import AlmacenReserva
from parking_app.services.auth_service import AuthService
from parking_app.services.cajones_service import CajonesService
from parking_app.services.emqx_admin_service import EmqxAdminService
from parking_app.services.mqtt_service import MqttService
from parking_app.services.reservas_service import ReservasService
from parking_app.viewmodels.admin_reservas_viewmodel import AdminReservasViewModel
from parking_app.viewmodels.cambiar_password_viewmodel import CambiarPasswordViewModel
from parking_app.viewmodels.escaner_viewmodel import EscanerViewModel
from parking_app.viewmodels.inicio_viewmodel import InicioViewModel
from parking_app.viewmodels.login_viewmodel import LoginViewModel
from parking_app.viewmodels.mi_reserva_viewmodel import MiReservaViewModel
from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel
from parking_app.viewmodels.perfil_viewmodel import PerfilViewModel
from parking_app.viewmodels.recuperar_password_viewmodel import RecuperarPasswordViewModel
from parking_app.viewmodels.registro_viewmodel import RegistroViewModel
from parking_app.viewmodels.reservar_viewmodel import ReservarViewModel
from parking_app.views import (
    admin_reservas_view,
    cambiar_password_view,
    escaner_view,
    inicio_view,
    login_view,
    mi_reserva_view,
    ocupacion_view,
    perfil_view,
    recuperar_password_view,
    registro_view,
    reservar_view,
)

logger = logging.getLogger(__name__)

RUTA_LOGIN = login_view.RUTA
RUTA_REGISTRO = registro_view.RUTA
RUTA_RECUPERAR = recuperar_password_view.RUTA
RUTA_INICIO = inicio_view.RUTA
RUTA_OCUPACION = ocupacion_view.RUTA
RUTA_PERFIL = perfil_view.RUTA
RUTA_CAMBIAR_PASSWORD = cambiar_password_view.RUTA
RUTA_RESERVAR = reservar_view.RUTA
RUTA_MI_RESERVA = mi_reserva_view.RUTA
RUTA_ADMIN_RESERVAS = admin_reservas_view.RUTA
RUTA_ESCANEAR = escaner_view.RUTA

# Pila de vistas para cada ruta: permite "regresar" con el botón de atrás.
PILAS: dict[str, list[str]] = {
    RUTA_LOGIN: [RUTA_LOGIN],
    RUTA_REGISTRO: [RUTA_LOGIN, RUTA_REGISTRO],
    RUTA_RECUPERAR: [RUTA_LOGIN, RUTA_RECUPERAR],
    RUTA_INICIO: [RUTA_INICIO],
    RUTA_OCUPACION: [RUTA_INICIO, RUTA_OCUPACION],
    RUTA_PERFIL: [RUTA_INICIO, RUTA_PERFIL],
    RUTA_CAMBIAR_PASSWORD: [RUTA_INICIO, RUTA_PERFIL, RUTA_CAMBIAR_PASSWORD],
    RUTA_RESERVAR: [RUTA_INICIO, RUTA_OCUPACION, RUTA_RESERVAR],
    RUTA_MI_RESERVA: [RUTA_INICIO, RUTA_MI_RESERVA],
    RUTA_ADMIN_RESERVAS: [RUTA_INICIO, RUTA_ADMIN_RESERVAS],
    RUTA_ESCANEAR: [RUTA_INICIO, RUTA_ADMIN_RESERVAS, RUTA_ESCANEAR],
}
RUTAS_PROTEGIDAS = {
    RUTA_INICIO, RUTA_OCUPACION, RUTA_PERFIL, RUTA_CAMBIAR_PASSWORD, RUTA_RESERVAR,
    RUTA_MI_RESERVA, RUTA_ADMIN_RESERVAS, RUTA_ESCANEAR,
}
# Módulo C: además de sesión, exigen el rol de administrador.
RUTAS_ADMINISTRADOR = {RUTA_ADMIN_RESERVAS, RUTA_ESCANEAR}


class Vista(Protocol):
    view: ft.View

    def montar(self) -> None: ...

    def desmontar(self) -> None: ...

# Clase representativa para la comunicación entre las clases View y ViewModel
class Router:
    def __init__(
        self,
        page: ft.Page,
        auth_service: AuthService,
        emqx_service: EmqxAdminService,
        cajones_service: CajonesService,
        mqtt_service: MqttService,
        timeout_nodo_segundos: int,
        reservas_service: ReservasService | None = None,
        almacen_reserva: AlmacenReserva | None = None,
    ) -> None:
        self._page = page
        self._auth = auth_service
        self._emqx = emqx_service
        self._cajones = cajones_service
        self._mqtt = mqtt_service
        self._timeout_nodo = timeout_nodo_segundos
        self._reservas = reservas_service or ReservasService(auth_service.token_acceso)
        self._almacen = almacen_reserva or AlmacenReserva()
        # Cajón que el estudiante tocó en el mapa; lo recibe la pantalla de reserva.
        self._cajon_a_reservar: str | None = None
        self._tareas: set[asyncio.Task[None]] = set()
        self._activas: dict[str, Vista] = {}
        self._ocupacion: OcupacionViewModel | None = None
        self._inicio_ocupacion: asyncio.Task[None] | None = None
        # ViewModel de Inicio: se refresca al editar el perfil (su vista sigue montada debajo).
        self._inicio: InicioViewModel | None = None
        # ViewModel de Reservas (administrador): se vuelve a consultar al regresar del escáner.
        self._admin_reservas: AdminReservasViewModel | None = None
        self._fabricas: dict[str, Callable[[], Vista]] = {
            RUTA_LOGIN: self._crear_login,
            RUTA_REGISTRO: self._crear_registro,
            RUTA_RECUPERAR: self._crear_recuperar,
            RUTA_INICIO: self._crear_inicio,
            RUTA_OCUPACION: self._crear_ocupacion,
            RUTA_PERFIL: self._crear_perfil,
            RUTA_CAMBIAR_PASSWORD: self._crear_cambiar_password,
            RUTA_RESERVAR: self._crear_reservar,
            RUTA_MI_RESERVA: self._crear_mi_reserva,
            RUTA_ADMIN_RESERVAS: self._crear_admin_reservas,
            RUTA_ESCANEAR: self._crear_escaner,
        }

    async def iniciar(self) -> None:
        self._page.on_route_change = self._on_route_change
        self._page.on_view_pop = self._on_view_pop
        destino = RUTA_INICIO if self._auth.hay_sesion_activa else RUTA_LOGIN
        if self._page.route == destino:
            self._mostrar(destino)
        else:
            await self.ir(destino)

    async def ir(self, ruta: str) -> None:
        await self._page.push_route(ruta)

    # --- Eventos de Flet ---

    async def _on_route_change(self, _e: ft.RouteChangeEvent) -> None:
        pedida = self._page.route
        ruta = pedida if pedida in PILAS else RUTA_LOGIN
        if pedida not in PILAS:
            logger.warning("Ruta desconocida %r", pedida)
        if ruta in RUTAS_PROTEGIDAS and not self._auth.hay_sesion_activa:
            # Diagnóstico: un salto inesperado al login significa que la sesión se perdió.
            logger.warning("Sin sesión activa al ir a %s: se muestra el login", pedida)
            ruta = RUTA_LOGIN
        # Con sesión abierta no se vuelve a las pantallas de acceso.
        if ruta not in RUTAS_PROTEGIDAS and self._auth.hay_sesion_activa:
            ruta = RUTA_INICIO
        if ruta in RUTAS_ADMINISTRADOR and not self._es_administrador():
            logger.warning("%s es solo para administradores", ruta)
            ruta = RUTA_INICIO
        if ruta != self._page.route:
            await self.ir(ruta)
            return
        self._mostrar(ruta)

    async def _on_view_pop(self, e: ft.ViewPopEvent) -> None:
        pila = PILAS.get(self._page.route, [RUTA_LOGIN])
        await self.ir(pila[-2] if len(pila) > 1 else pila[0])

    # --- Pila de vistas ---

    def _mostrar(self, ruta: str) -> None:
        pila = PILAS[ruta]
        volviendo_del_escaner = RUTA_ESCANEAR in self._activas and RUTA_ESCANEAR not in pila
        # Al regresar al menú (de reservar, de "Mi reserva"...), la tarjeta "Mi reserva" se pone al día.
        volviendo_a_inicio = (pila == [RUTA_INICIO] and RUTA_INICIO in self._activas
                              and len(self._activas) > 1)
        for r in [r for r in self._activas if r not in pila]:
            self._activas.pop(r).desmontar()
        if not RUTAS_PROTEGIDAS & set(pila):
            # Fuera de la zona con sesión (p. ej. tras cerrar sesión): se cierra MQTT.
            self._detener_ocupacion()
        for r in pila:
            if r not in self._activas:
                vista = self._fabricas[r]()
                vista.montar()
                self._activas[r] = vista
        self._page.views.clear()
        self._page.views.extend(self._activas[r].view for r in pila)
        self._page.update()
        if volviendo_del_escaner and RUTA_ADMIN_RESERVAS in pila and self._admin_reservas is not None:
            # La lista quedó montada debajo del escáner: la llegada recién registrada
            # no espera al aviso de MQTT ni a la consulta cada 30 s.
            self._iniciar_en_segundo_plano(self._admin_reservas.actualizar())
        if volviendo_a_inicio and self._inicio is not None:
            self._iniciar_en_segundo_plano(self._inicio.actualizar_reserva())

    # --- Fábricas ---

    def _crear_login(self) -> Vista:
        vm = LoginViewModel(
            self._auth,
            al_iniciar_sesion=lambda: self.ir(RUTA_INICIO),
            al_ir_a_registro=lambda: self.ir(RUTA_REGISTRO),
            al_ir_a_recuperar=lambda: self.ir(RUTA_RECUPERAR),
        )
        return login_view.LoginView(vm)

    def _crear_registro(self) -> Vista:
        vm = RegistroViewModel(
            self._auth,
            self._emqx,
            al_ir_a_login=lambda: self.ir(RUTA_LOGIN),
            al_ir_a_recuperar=lambda: self.ir(RUTA_RECUPERAR),
        )
        return registro_view.RegistroView(vm)

    def _crear_recuperar(self) -> Vista:
        vm = RecuperarPasswordViewModel(
            self._auth, self._emqx, al_ir_a_login=lambda: self.ir(RUTA_LOGIN)
        )
        return recuperar_password_view.RecuperarPasswordView(vm)

    def _crear_inicio(self) -> Vista:
        vm = InicioViewModel(
            self._auth,
            self._ocupacion_de_sesion(),
            al_ir_a_ocupacion=lambda: self.ir(RUTA_OCUPACION),
            al_cerrar_sesion=lambda: self.ir(RUTA_LOGIN),
            al_ir_a_perfil=lambda: self.ir(RUTA_PERFIL),
            al_ir_a_reservas=lambda: self.ir(RUTA_ADMIN_RESERVAS),
            reservas_service=self._reservas,
            almacen=self._almacen,
            al_ir_a_mi_reserva=lambda: self.ir(RUTA_MI_RESERVA),
        )
        self._inicio = vm
        self._iniciar_en_segundo_plano(vm.iniciar())
        return inicio_view.InicioView(vm)

    def _crear_ocupacion(self) -> Vista:
        return ocupacion_view.OcupacionView(self._ocupacion_de_sesion())

    def _crear_perfil(self) -> Vista:
        vm = PerfilViewModel(
            self._auth,
            al_regresar=lambda: self.ir(RUTA_INICIO),
            al_ir_a_cambiar_password=lambda: self.ir(RUTA_CAMBIAR_PASSWORD),
            al_guardar=self._perfil_actualizado,
        )
        return perfil_view.PerfilView(vm)

    def _crear_cambiar_password(self) -> Vista:
        vm = CambiarPasswordViewModel(
            self._auth,
            self._emqx,
            al_regresar=lambda: self.ir(RUTA_PERFIL),
            al_cambiar=self._password_cambiada,
        )
        return cambiar_password_view.CambiarPasswordView(vm)

    def _crear_reservar(self) -> Vista:
        vm = ReservarViewModel(
            self._auth,
            self._ocupacion_de_sesion(),
            self._reservas,
            self._almacen,
            al_salir=lambda: self.ir(RUTA_OCUPACION),
            al_reserva_creada=lambda: self.ir(RUTA_MI_RESERVA),
            al_ver_reserva=lambda: self.ir(RUTA_MI_RESERVA),
            etiqueta_inicial=self._cajon_a_reservar,
        )
        self._cajon_a_reservar = None
        # Aparta el cajón tocado; corre dentro del handler async de cambio de ruta.
        tarea = asyncio.get_running_loop().create_task(vm.iniciar())
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)
        return reservar_view.ReservarView(vm)

    def _crear_mi_reserva(self) -> Vista:
        vm = MiReservaViewModel(
            self._auth,
            self._reservas,
            self._almacen,
            al_salir=lambda: self.ir(RUTA_INICIO),
            al_ver_cajones=lambda: self.ir(RUTA_OCUPACION),
            ocupacion=self._ocupacion_de_sesion(),
        )
        # Lee la copia local, consulta el servidor y arranca la cuenta regresiva.
        tarea = asyncio.get_running_loop().create_task(vm.iniciar())
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)
        return mi_reserva_view.MiReservaView(vm)

    def _crear_admin_reservas(self) -> Vista:
        vm = AdminReservasViewModel(
            self._reservas,
            al_regresar=lambda: self.ir(RUTA_INICIO),
            al_escanear=lambda: self.ir(RUTA_ESCANEAR),
            ocupacion=self._ocupacion_de_sesion(),
        )
        self._admin_reservas = vm
        self._iniciar_en_segundo_plano(vm.iniciar())
        return admin_reservas_view.AdminReservasView(vm)

    def _crear_escaner(self) -> Vista:
        vm = EscanerViewModel(
            self._reservas,
            al_regresar=lambda: self.ir(RUTA_ADMIN_RESERVAS),
            al_ver_reservas=lambda: self.ir(RUTA_ADMIN_RESERVAS),
        )
        # flet-camera solo funciona en el teléfono; en la PC se escribe el código.
        con_camara = self._page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
        return escaner_view.EscanerView(vm, con_camara=con_camara)

    def _iniciar_en_segundo_plano(self, corrutina) -> None:
        # Corre dentro del handler async de cambio de ruta: hay loop activo.
        tarea = asyncio.get_running_loop().create_task(corrutina)
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)

    def _es_administrador(self) -> bool:
        usuario = self._auth.usuario_actual
        return usuario is not None and usuario.rol == Rol.ADMINISTRADOR

    async def _ir_a_reservar(self, etiqueta: str) -> None:
        self._cajon_a_reservar = etiqueta
        await self.ir(RUTA_RESERVAR)

    def _perfil_actualizado(self) -> None:
        if self._inicio is not None:
            self._inicio.refrescar()

    def _password_cambiada(self) -> None:
        # paho reconectaría con la contraseña anterior y el broker la rechazaría.
        if self._ocupacion is not None:
            self._ocupacion.reconectar_mqtt()

    # --- Estado de ocupación compartido durante la sesión ---

    def _ocupacion_de_sesion(self) -> OcupacionViewModel:
        """Un solo OcupacionViewModel (y una sola conexión MQTT) para Inicio y Ocupación."""
        if self._ocupacion is None:
            self._ocupacion = OcupacionViewModel(
                self._auth,
                self._cajones,
                self._mqtt,
                self._emqx,
                timeout_nodo_segundos=self._timeout_nodo,
                al_ir_a_inicio=lambda: self.ir(RUTA_INICIO),
                al_reservar=self._ir_a_reservar,
            )
            # Se crea dentro del handler async de cambio de ruta: hay loop activo.
            self._inicio_ocupacion = asyncio.get_running_loop().create_task(
                self._ocupacion.iniciar()
            )
        return self._ocupacion

    def _detener_ocupacion(self) -> None:
        if self._inicio_ocupacion is not None:
            self._inicio_ocupacion.cancel()
            self._inicio_ocupacion = None
        if self._ocupacion is not None:
            self._ocupacion.detener()
            self._ocupacion = None
        self._inicio = None
