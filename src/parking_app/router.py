"""Navegación entre pantallas y guardia de sesión."""

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

import flet as ft

from parking_app.services.auth_service import AuthService
from parking_app.services.cajones_service import CajonesService
from parking_app.services.emqx_admin_service import EmqxAdminService
from parking_app.services.mqtt_service import MqttService
from parking_app.viewmodels.inicio_viewmodel import InicioViewModel
from parking_app.viewmodels.login_viewmodel import LoginViewModel
from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel
from parking_app.viewmodels.recuperar_password_viewmodel import RecuperarPasswordViewModel
from parking_app.viewmodels.registro_viewmodel import RegistroViewModel
from parking_app.views import (
    inicio_view,
    login_view,
    ocupacion_view,
    recuperar_password_view,
    registro_view,
)

logger = logging.getLogger(__name__)

RUTA_LOGIN = login_view.RUTA
RUTA_REGISTRO = registro_view.RUTA
RUTA_RECUPERAR = recuperar_password_view.RUTA
RUTA_INICIO = inicio_view.RUTA
RUTA_OCUPACION = ocupacion_view.RUTA

# Pila de vistas para cada ruta: permite "regresar" con el botón de atrás.
PILAS: dict[str, list[str]] = {
    RUTA_LOGIN: [RUTA_LOGIN],
    RUTA_REGISTRO: [RUTA_LOGIN, RUTA_REGISTRO],
    RUTA_RECUPERAR: [RUTA_LOGIN, RUTA_RECUPERAR],
    RUTA_INICIO: [RUTA_INICIO],
    RUTA_OCUPACION: [RUTA_INICIO, RUTA_OCUPACION],
}
RUTAS_PROTEGIDAS = {RUTA_INICIO, RUTA_OCUPACION}


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
    ) -> None:
        self._page = page
        self._auth = auth_service
        self._emqx = emqx_service
        self._cajones = cajones_service
        self._mqtt = mqtt_service
        self._timeout_nodo = timeout_nodo_segundos
        self._activas: dict[str, Vista] = {}
        self._ocupacion: OcupacionViewModel | None = None
        self._inicio_ocupacion: asyncio.Task[None] | None = None
        self._fabricas: dict[str, Callable[[], Vista]] = {
            RUTA_LOGIN: self._crear_login,
            RUTA_REGISTRO: self._crear_registro,
            RUTA_RECUPERAR: self._crear_recuperar,
            RUTA_INICIO: self._crear_inicio,
            RUTA_OCUPACION: self._crear_ocupacion,
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
        ruta = self._page.route if self._page.route in PILAS else RUTA_LOGIN
        if ruta in RUTAS_PROTEGIDAS and not self._auth.hay_sesion_activa:
            ruta = RUTA_LOGIN
        # Con sesión abierta no se vuelve a las pantallas de acceso.
        if ruta not in RUTAS_PROTEGIDAS and self._auth.hay_sesion_activa:
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
        )
        return inicio_view.InicioView(vm)

    def _crear_ocupacion(self) -> Vista:
        return ocupacion_view.OcupacionView(self._ocupacion_de_sesion())

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
