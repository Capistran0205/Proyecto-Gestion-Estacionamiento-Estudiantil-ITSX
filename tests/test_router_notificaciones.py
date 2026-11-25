"""Notificaciones push en el router: token del dispositivo y ruteo al tocar un aviso."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from parking_app.services.notificaciones_service import AvisoPush
from test_router import _router, _router_con_rol


class NotificacionesFalsas:
    def __init__(self, token="tok-1", inicial=None):
        self.token = token
        self.inicial = inicial
        self.llamadas = []
        self.manejadores = None

    async def iniciar(self, page, al_renovar_token, al_mensaje, al_tocar):
        self.llamadas.append("iniciar")
        self.manejadores = (al_renovar_token, al_mensaje, al_tocar)
        return self.token

    async def aviso_inicial(self):
        return self.inicial

    async def olvidar_token(self):
        self.llamadas.append("olvidar_token")


def _conectar(router, pagina):
    # Lo que hace Router.iniciar() sin navegar: engancha los eventos de la página.
    pagina.on_route_change = router._on_route_change
    pagina.on_view_pop = router._on_view_pop


def _router_con_push(rol="estudiante", token="tok-1", inicial=None):
    router, pagina = _router_con_rol(rol)
    _conectar(router, pagina)
    router._reservas.reserva_vigente.return_value = None
    router._reservas.obtener_reserva.return_value = None
    router._almacen = MagicMock()
    router._almacen.leer.return_value = None
    router._notificaciones = NotificacionesFalsas(token, inicial)
    router._dispositivos = MagicMock()
    return router, pagina


def test_tras_iniciar_sesion_se_registra_el_token_del_dispositivo():
    async def escenario():
        router, pagina = _router_con_push()
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)
        assert pagina.rutas == ["/inicio"]
        router._dispositivos.registrar_token.assert_called_once_with("tok-1")
        assert router._token_fcm == "tok-1"
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_sin_servicio_de_notificaciones_el_login_solo_navega():
    async def escenario():
        router, pagina = _router_con_rol("estudiante")
        _conectar(router, pagina)
        router._reservas.reserva_vigente.return_value = None
        router._almacen = MagicMock()
        router._almacen.leer.return_value = None
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)
        assert pagina.rutas == ["/inicio"]
        assert router._token_fcm is None
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_si_falla_el_registro_del_token_la_app_sigue():
    async def escenario():
        router, pagina = _router_con_push()
        router._dispositivos.registrar_token.side_effect = RuntimeError("sin red")
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)
        assert pagina.rutas == ["/inicio"]
        assert router._token_fcm is None
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_sin_permiso_no_hay_token_ni_registro():
    async def escenario():
        router, _ = _router_con_push(token=None)
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)
        router._dispositivos.registrar_token.assert_not_called()
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_al_renovarse_el_token_se_vuelve_a_registrar():
    async def escenario():
        router, _ = _router_con_push()
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)
        await router._notificaciones.manejadores[0]("tok-2")
        router._dispositivos.registrar_token.assert_called_with("tok-2")
        assert router._token_fcm == "tok-2"
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_el_token_se_borra_antes_de_cerrar_la_sesion():
    async def escenario():
        router, _ = _router_con_push()
        orden = []
        router._dispositivos.borrar_token.side_effect = lambda t: orden.append(("borrar", t))
        router._auth.cerrar_sesion.side_effect = lambda: orden.append(("cerrar",))
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)

        await router._inicio.cerrar_sesion()

        assert orden == [("borrar", "tok-1"), ("cerrar",)]
        assert router._token_fcm is None
        assert "olvidar_token" in router._notificaciones.llamadas
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_si_falla_el_borrado_del_token_igual_se_cierra_la_sesion():
    async def escenario():
        router, _ = _router_con_push()
        router._dispositivos.borrar_token.side_effect = RuntimeError("sin red")
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)

        await router._inicio.cerrar_sesion()

        router._auth.cerrar_sesion.assert_called_once()
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_un_token_renovado_durante_el_cierre_de_sesion_no_se_registra():
    async def escenario():
        router, _ = _router_con_push()
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)
        router._dispositivos.registrar_token.reset_mock()

        await router._quitar_token_push()
        await router._notificaciones.manejadores[0]("tok-nuevo")

        router._dispositivos.registrar_token.assert_not_called()
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


@pytest.mark.parametrize(
    "tipo", ["retraso_llegada", "reserva_expirada", "fin_proximo", "fin_alcanzado"]
)
def test_tocar_un_aviso_lleva_al_estudiante_a_su_reserva(tipo):
    async def escenario():
        router, pagina = _router_con_push()
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)
        al_tocar = router._notificaciones.manejadores[2]

        await al_tocar(AvisoPush(tipo=tipo, id_reserva="r1", id_cajon="2"))
        await asyncio.sleep(0.05)

        assert pagina.rutas == ["/inicio", "/mi-reserva"]
        router._activas["/mi-reserva"].desmontar()
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_el_aviso_de_conflicto_lleva_al_administrador_a_las_reservas():
    async def escenario():
        router, pagina = _router_con_push(rol="administrador")
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)

        await router._aviso_tocado(AvisoPush(tipo="conflicto_sensor", id_cajon="2"))
        await asyncio.sleep(0.05)

        assert pagina.rutas == ["/inicio", "/admin/reservas"]
        router._activas["/admin/reservas"].desmontar()
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_otros_avisos_no_mueven_al_administrador():
    async def escenario():
        router, pagina = _router_con_push(rol="administrador")
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)

        await router._aviso_tocado(AvisoPush(tipo="retraso_llegada"))

        assert pagina.rutas == ["/inicio"]
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_sin_sesion_un_aviso_tocado_no_navega():
    async def escenario():
        router, pagina, _, _ = _router()
        await router.iniciar()

        await router._aviso_tocado(AvisoPush(tipo="retraso_llegada"))

        assert pagina.rutas == ["/login"]

    asyncio.run(escenario())


def test_la_notificacion_que_abrio_la_app_se_atiende_una_sola_vez():
    async def escenario():
        router, pagina = _router_con_push(inicial=AvisoPush(tipo="fin_proximo", id_reserva="r1"))
        await router._sesion_iniciada()
        await asyncio.sleep(0.05)
        assert pagina.rutas == ["/inicio", "/mi-reserva"]

        # Al volver a entrar en la misma ejecución ya no se repite el salto.
        await router.ir("/inicio")
        router._notificaciones.inicial = AvisoPush(tipo="fin_proximo", id_reserva="r1")
        await router._activar_notificaciones()
        assert pagina.rutas == ["/inicio"]
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())


def test_un_aviso_con_la_app_abierta_actualiza_mi_reserva():
    async def escenario():
        router, _ = _router_con_push()
        await router._sesion_iniciada()
        await router.ir("/mi-reserva")
        await asyncio.sleep(0.05)
        router._mi_reserva.actualizar = AsyncMock()

        await router._aviso_en_primer_plano(AvisoPush(tipo="fin_proximo"))

        router._mi_reserva.actualizar.assert_awaited_once()
        router._activas["/mi-reserva"].desmontar()
        router._activas["/inicio"].desmontar()

    asyncio.run(escenario())
