import json

import httpx
import pytest

from parking_app.services.dispositivos_service import DispositivosService
from parking_app.services.reservas_service import ReservaError, ReservasNoDisponiblesError

URL = "https://proyecto.supabase.co"


def _servicio(manejador, token="jwt"):
    peticiones = []

    def registrar(request):
        peticiones.append(request)
        return manejador(request)

    servicio = DispositivosService(
        token_factory=lambda: token,
        url_factory=lambda: (URL, "anon-key"),
        transporte=httpx.MockTransport(registrar),
    )
    return servicio, peticiones


def test_registrar_llama_a_la_rpc_con_el_jwt_y_el_token():
    servicio, peticiones = _servicio(lambda r: httpx.Response(204))

    servicio.registrar_token("tok-1")

    [p] = peticiones
    assert p.method == "POST"
    assert str(p.url) == f"{URL}/rest/v1/rpc/registrar_token_fcm"
    assert p.headers["authorization"] == "Bearer jwt"
    assert p.headers["apikey"] == "anon-key"
    assert json.loads(p.content) == {"p_token": "tok-1", "p_plataforma": "android"}


def test_borrar_elimina_solo_la_fila_de_ese_token():
    servicio, peticiones = _servicio(lambda r: httpx.Response(204))

    servicio.borrar_token("tok-1")

    [p] = peticiones
    assert p.method == "DELETE"
    assert p.url.path == "/rest/v1/dispositivos_fcm"
    assert p.url.params["token"] == "eq.tok-1"
    assert p.headers["authorization"] == "Bearer jwt"


def test_sin_sesion_no_se_llama_al_servidor():
    servicio, peticiones = _servicio(lambda r: httpx.Response(204), token=None)

    with pytest.raises(ReservaError) as e:
        servicio.registrar_token("tok-1")

    assert e.value.codigo == "NO_AUTENTICADO"
    assert peticiones == []


def test_un_401_se_reporta_como_sesion_expirada():
    servicio, _ = _servicio(lambda r: httpx.Response(401, json={"message": "JWT expired"}))

    with pytest.raises(ReservaError) as e:
        servicio.borrar_token("tok-1")

    assert e.value.codigo == "NO_AUTENTICADO"


def test_un_error_del_servidor_no_es_una_regla_de_negocio():
    servicio, _ = _servicio(lambda r: httpx.Response(500, text="boom"))

    with pytest.raises(ReservasNoDisponiblesError) as e:
        servicio.registrar_token("tok-1")

    assert not e.value.sin_red


def test_sin_red_se_marca_como_tal():
    def sin_red(request):
        raise httpx.ConnectError("sin red")

    servicio, _ = _servicio(sin_red)

    with pytest.raises(ReservasNoDisponiblesError) as e:
        servicio.registrar_token("tok-1")

    assert e.value.sin_red
