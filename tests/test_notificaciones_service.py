import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import flet as ft

from parking_app.core.config import ConfigFirebase
from parking_app.services.notificaciones_service import AvisoPush, NotificacionesService

CONFIG = ConfigFirebase("api", "app", "sender", "proyecto")


def _pagina(plataforma=ft.PagePlatform.ANDROID):
    return SimpleNamespace(platform=plataforma)


class FcmFalso:
    def __init__(self, **manejadores):
        self.manejadores = manejadores
        self.inicializar = AsyncMock()
        self.pedir_permiso = AsyncMock(return_value=True)
        self.obtener_token = AsyncMock(return_value="tok-1")
        self.borrar_token = AsyncMock()
        self.mensaje_inicial = AsyncMock(return_value=None)


def _servicio(config=CONFIG):
    creados = []

    def fabrica(**manejadores):
        creados.append(FcmFalso(**manejadores))
        return creados[-1]

    return NotificacionesService(config, fabrica_fcm=fabrica), creados


def _iniciar(servicio, pagina=None):
    return asyncio.run(
        servicio.iniciar(pagina or _pagina(), AsyncMock(), AsyncMock(), AsyncMock())
    )


def test_el_aviso_toma_tipo_y_reserva_del_data_que_llega_como_texto():
    aviso = AvisoPush.desde(
        "Tu reserva", "vence pronto", {"tipo": "fin_proximo", "id_reserva": "r1", "id_cajon": 3}
    )

    assert aviso == AvisoPush("fin_proximo", "r1", "3", "Tu reserva", "vence pronto")


def test_un_aviso_sin_data_no_falla():
    assert AvisoPush.desde(None, None, None) == AvisoPush()
    assert AvisoPush.desde_mapa({"titulo": "x", "datos": {"tipo": ""}}) == AvisoPush(titulo="x")


def test_en_pc_no_se_activa_nada():
    servicio, creados = _servicio()

    assert _iniciar(servicio, _pagina(ft.PagePlatform.WINDOWS)) is None
    assert creados == [] and not servicio.activa


def test_sin_variables_de_firebase_queda_apagado():
    servicio, creados = _servicio(config=None)

    assert _iniciar(servicio) is None
    assert creados == []


def test_inicia_firebase_pide_permiso_y_devuelve_el_token():
    servicio, creados = _servicio()

    assert _iniciar(servicio) == "tok-1"

    creados[0].inicializar.assert_awaited_once_with("api", "app", "sender", "proyecto")
    creados[0].pedir_permiso.assert_awaited_once()


def test_sin_permiso_no_hay_token():
    servicio, creados = _servicio()
    asyncio.run(servicio.iniciar(_pagina(), AsyncMock(), AsyncMock(), AsyncMock()))
    creados[0].pedir_permiso.return_value = False

    assert _iniciar(servicio) is None
    creados[0].obtener_token.assert_awaited_once()  # solo el de la primera vuelta


def test_si_la_extension_falla_no_se_propaga_el_error():
    def fabrica(**_):
        raise ImportError("flet_fcm no instalado")

    servicio = NotificacionesService(CONFIG, fabrica_fcm=fabrica)

    assert _iniciar(servicio) is None
    assert not servicio.activa


def test_el_control_se_crea_una_sola_vez_aunque_se_inicie_varias():
    servicio, creados = _servicio()

    _iniciar(servicio)
    _iniciar(servicio)

    assert len(creados) == 1


def test_los_eventos_de_la_extension_llegan_normalizados_a_los_callbacks():
    servicio, creados = _servicio()
    renovar, mensaje, tocar = AsyncMock(), AsyncMock(), AsyncMock()
    asyncio.run(servicio.iniciar(_pagina(), renovar, mensaje, tocar))
    manejadores = creados[0].manejadores
    evento = SimpleNamespace(titulo="t", cuerpo="c", datos={"tipo": "retraso_llegada"})

    async def escenario():
        await manejadores["on_token_refresh"](SimpleNamespace(token="tok-2"))
        await manejadores["on_message"](evento)
        await manejadores["on_message_opened"](evento)

    asyncio.run(escenario())

    renovar.assert_awaited_once_with("tok-2")
    mensaje.assert_awaited_once_with(AvisoPush("retraso_llegada", None, None, "t", "c"))
    tocar.assert_awaited_once_with(AvisoPush("retraso_llegada", None, None, "t", "c"))


def test_un_callback_que_falla_no_rompe_el_evento():
    servicio, creados = _servicio()
    asyncio.run(servicio.iniciar(_pagina(), AsyncMock(), AsyncMock(),
                                 MagicMock(side_effect=RuntimeError("boom"))))

    asyncio.run(creados[0].manejadores["on_message_opened"](SimpleNamespace(datos={})))


def test_la_notificacion_inicial_se_lee_de_la_extension():
    servicio, creados = _servicio()
    _iniciar(servicio)
    creados[0].mensaje_inicial.return_value = {
        "titulo": "t", "cuerpo": "c", "datos": {"tipo": "fin_alcanzado", "id_reserva": "r9"},
    }

    aviso = asyncio.run(servicio.aviso_inicial())

    assert aviso == AvisoPush("fin_alcanzado", "r9", None, "t", "c")


def test_olvidar_el_token_no_falla_si_firebase_responde_error():
    servicio, creados = _servicio()
    _iniciar(servicio)
    creados[0].borrar_token.side_effect = RuntimeError("sin red")

    asyncio.run(servicio.olvidar_token())
