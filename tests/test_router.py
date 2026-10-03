"""Navegación y ciclo de vida de la conexión MQTT con una página falsa."""

import asyncio
from unittest.mock import MagicMock

from parking_app.router import Router
from parking_app.services.auth_service import CredencialesMqtt


class PaginaFalsa:
    def __init__(self) -> None:
        self.route = "/"
        self.views: list = []
        self.on_route_change = None
        self.on_view_pop = None

    async def push_route(self, ruta: str) -> None:
        self.route = ruta
        await self.on_route_change(None)

    def update(self) -> None:
        pass

    @property
    def rutas(self) -> list[str]:
        return [v.route for v in self.views]


def _router(con_sesion=False):
    pagina, auth, mqtt, cajones = PaginaFalsa(), MagicMock(), MagicMock(), MagicMock()
    auth.hay_sesion_activa = con_sesion
    auth.usuario_actual = None
    auth.credenciales_mqtt = CredencialesMqtt("ana@itsx.edu.mx", "x")
    cajones.obtener_estado_actual.return_value = []
    router = Router(pagina, auth, MagicMock(), cajones, mqtt, timeout_nodo_segundos=60)
    return router, pagina, auth, mqtt


def test_sin_sesion_no_se_llega_a_ocupacion():
    async def escenario():
        router, pagina, _, mqtt = _router()
        await router.iniciar()
        assert pagina.rutas == ["/login"]
        await router.ir("/ocupacion")
        assert pagina.route == "/login"
        mqtt.conectar.assert_not_called()

    asyncio.run(escenario())


def test_registro_se_apila_sobre_login():
    async def escenario():
        router, pagina, _, _ = _router()
        await router.iniciar()
        await router.ir("/registro")
        assert pagina.rutas == ["/login", "/registro"]

    asyncio.run(escenario())


def test_una_sola_conexion_mqtt_para_inicio_y_ocupacion_y_se_cierra_al_salir():
    async def escenario():
        router, pagina, auth, mqtt = _router(con_sesion=True)
        await router.iniciar()
        await asyncio.sleep(0)
        assert pagina.rutas == ["/inicio"]

        await router.ir("/ocupacion")
        await router.ir("/inicio")
        await router.ir("/ocupacion")
        await asyncio.sleep(0)
        assert pagina.rutas == ["/inicio", "/ocupacion"]
        assert mqtt.conectar.call_count == 1

        auth.hay_sesion_activa = False  # cerrar sesión
        await router.ir("/login")
        assert pagina.rutas == ["/login"]
        mqtt.desconectar.assert_called()
        assert router._ocupacion is None

    asyncio.run(escenario())


def test_con_sesion_no_se_vuelve_al_login():
    async def escenario():
        router, pagina, _, _ = _router(con_sesion=True)
        await router.iniciar()
        await router.ir("/login")
        assert pagina.route == "/inicio"

    asyncio.run(escenario())
