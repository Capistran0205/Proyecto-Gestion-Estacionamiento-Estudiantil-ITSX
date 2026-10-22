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
        self.platform = None  # ni Android ni iOS: el escáner usa la captura manual

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


def test_perfil_y_cambiar_password_se_apilan_sobre_inicio_y_requieren_sesion():
    async def escenario():
        router, pagina, _, _ = _router()
        await router.iniciar()
        await router.ir("/perfil")
        assert pagina.route == "/login"

        router, pagina, _, _ = _router(con_sesion=True)
        await router.iniciar()
        await router.ir("/perfil")
        assert pagina.rutas == ["/inicio", "/perfil"]
        await router.ir("/perfil/password")
        assert pagina.rutas == ["/inicio", "/perfil", "/perfil/password"]
        await router.ir("/perfil")
        assert pagina.rutas == ["/inicio", "/perfil"]

    asyncio.run(escenario())


def test_cambiar_password_reconecta_mqtt_y_guardar_perfil_refresca_inicio():
    async def escenario():
        router, _, _, mqtt = _router(con_sesion=True)
        await router.iniciar()
        await asyncio.sleep(0)
        await router.ir("/perfil")

        router._password_cambiada()
        assert mqtt.conectar.call_count == 2

        escucha = MagicMock()
        router._inicio.add_listener(escucha)
        router._perfil_actualizado()
        escucha.assert_called_once()

    asyncio.run(escenario())


def test_tocar_un_cajon_libre_abre_la_reserva_y_salir_libera():
    async def escenario():
        pagina, auth, mqtt, cajones = PaginaFalsa(), MagicMock(), MagicMock(), MagicMock()
        auth.hay_sesion_activa = True
        auth.usuario_actual = None
        auth.credenciales_mqtt = CredencialesMqtt("ana@itsx.edu.mx", "x")
        cajones.obtener_estado_actual.return_value = []
        reservas = MagicMock()
        reservas.bloquear_cajon.side_effect = RuntimeError("se prueba solo la navegación")
        router = Router(pagina, auth, MagicMock(), cajones, mqtt, timeout_nodo_segundos=60,
                        reservas_service=reservas, almacen_reserva=MagicMock())
        await router.iniciar()
        await router.ir("/ocupacion")

        await router._ir_a_reservar("C2")
        assert pagina.rutas == ["/inicio", "/ocupacion", "/reservar"]
        vista = router._activas["/reservar"]
        assert vista._vm._etiqueta_inicial == "C2"

        await router.ir("/ocupacion")
        assert pagina.rutas == ["/inicio", "/ocupacion"]

    asyncio.run(escenario())


def test_mi_reserva_se_apila_sobre_inicio_y_al_salir_detiene_la_cuenta_regresiva():
    async def escenario():
        router, pagina, _, _ = _router()
        await router.iniciar()
        await router.ir("/mi-reserva")
        assert pagina.route == "/login"

        router, pagina, _, _ = _router(con_sesion=True)
        await router.iniciar()
        await router.ir("/mi-reserva")
        assert pagina.rutas == ["/inicio", "/mi-reserva"]
        vm = router._activas["/mi-reserva"]._vm
        await asyncio.sleep(0.05)
        await router.ir("/inicio")
        assert pagina.rutas == ["/inicio"]
        assert vm._liberado and vm._ciclo is None

    asyncio.run(escenario())


def _router_con_rol(rol):
    from parking_app.models.usuario import MedioTransporte, Rol, Usuario

    router, pagina, auth, mqtt = _router(con_sesion=True)
    auth.usuario_actual = Usuario("uid", "Ana", "Pérez", None, "ana@itsx.edu.mx",
                                  MedioTransporte.VEHICULO, rol=Rol(rol))
    router._reservas = MagicMock()
    router._reservas.reservas_activas.return_value = []
    return router, pagina


def test_un_estudiante_no_entra_a_las_pantallas_del_administrador():
    async def escenario():
        router, pagina = _router_con_rol("estudiante")
        await router.iniciar()
        await router.ir("/admin/reservas")
        assert pagina.rutas == ["/inicio"]
        await router.ir("/admin/escanear")
        assert pagina.rutas == ["/inicio"]

    asyncio.run(escenario())


def test_el_administrador_llega_a_reservas_y_al_escaner():
    async def escenario():
        router, pagina = _router_con_rol("administrador")
        await router.iniciar()
        assert router._inicio.es_administrador
        await router._inicio.ir_a_reservas()
        assert pagina.rutas == ["/inicio", "/admin/reservas"]
        await router.ir("/admin/escanear")
        assert pagina.rutas == ["/inicio", "/admin/reservas", "/admin/escanear"]
        escaner = router._activas["/admin/escanear"]
        assert escaner._camara is None  # en la PC no hay cámara
        await escaner._vm.ver_reservas()
        assert pagina.rutas == ["/inicio", "/admin/reservas"]
        await asyncio.sleep(0.05)
        await router.ir("/inicio")
        assert pagina.rutas == ["/inicio"]

    asyncio.run(escenario())


def test_al_volver_al_menu_se_consulta_la_reserva_del_estudiante():
    async def escenario():
        router, pagina = _router_con_rol("estudiante")
        router._reservas.reserva_vigente.return_value = None
        router._reservas.obtener_reserva.return_value = None
        router._almacen = MagicMock()
        router._almacen.leer.return_value = None
        await router.iniciar()
        await asyncio.sleep(0.05)  # carga inicial de la tarjeta "Mi reserva"
        consultas = router._reservas.reserva_vigente.call_count
        assert consultas >= 1

        await router.ir("/mi-reserva")
        await asyncio.sleep(0.05)
        consultas = router._reservas.reserva_vigente.call_count
        await router.ir("/inicio")
        await asyncio.sleep(0.05)
        assert pagina.rutas == ["/inicio"]
        assert router._reservas.reserva_vigente.call_count == consultas + 1
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_al_volver_del_escaner_se_consulta_la_lista_de_reservas():
    async def escenario():
        router, pagina = _router_con_rol("administrador")
        await router.iniciar()
        await router.ir("/admin/reservas")
        await asyncio.sleep(0.05)  # carga inicial de la lista
        consultas = router._reservas.reservas_activas.call_count
        await router.ir("/admin/escanear")
        await asyncio.sleep(0.05)
        assert router._reservas.reservas_activas.call_count == consultas

        # Con el gesto de regresar (view pop), sin pasar por el ViewModel del escáner
        await pagina.on_view_pop(None)
        await asyncio.sleep(0.05)
        assert pagina.rutas == ["/inicio", "/admin/reservas"]
        assert router._reservas.reservas_activas.call_count == consultas + 1
        router._activas["/admin/reservas"].desmontar()

    asyncio.run(escenario())