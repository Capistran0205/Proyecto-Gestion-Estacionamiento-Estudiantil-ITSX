import json

import httpx
import pytest

from parking_app.core.config import ConfigEmqx
from parking_app.services.emqx_admin_service import EmqxAdminService, EmqxError

TOPICO = "infraestructura/pruebaiot/prueba1"
CORREO = "ana@itsx.edu.mx"


def _servicio(manejador, url="https://broker.ejemplo:18083"):
    peticiones = []

    def registrar(request: httpx.Request) -> httpx.Response:
        peticiones.append(request)
        return manejador(request)

    servicio = EmqxAdminService(
        config_factory=lambda: ConfigEmqx(url, "key", "secret"),
        topico_factory=lambda: TOPICO,
        transporte=httpx.MockTransport(registrar),
    )
    return servicio, peticiones


def test_crea_usuario_y_acl_de_solo_suscripcion():
    servicio, peticiones = _servicio(lambda r: httpx.Response(201, json={}))

    servicio.crear_credencial(CORREO, "Segura#2026")

    usuario, acl = peticiones
    assert usuario.method == "POST"
    assert usuario.url.path == "/api/v5/authentication/password_based:built_in_database/users"
    assert json.loads(usuario.content) == {
        "user_id": CORREO,
        "password": "Segura#2026",
        "is_superuser": False,
    }
    assert usuario.headers["authorization"].startswith("Basic ")

    assert acl.url.path == "/api/v5/authorization/sources/built_in_database/rules/users"
    reglas = json.loads(acl.content)[0]["rules"]
    assert reglas[0] == {"topic": TOPICO, "permission": "allow", "action": "subscribe"}
    assert reglas[-1] == {"topic": "#", "permission": "deny", "action": "all"}


def test_si_ya_existe_actualiza_con_put():
    def manejador(r):
        return httpx.Response(409 if r.method == "POST" else 200, json={})

    servicio, peticiones = _servicio(manejador, url="https://broker.ejemplo/api/v5/")

    servicio.crear_credencial(CORREO, "Segura#2026")

    metodos = [(p.method, p.url.raw_path.decode()) for p in peticiones]
    assert metodos[1] == (
        "PUT",
        "/api/v5/authentication/password_based:built_in_database/users/ana%40itsx.edu.mx",
    )
    assert metodos[3][0] == "PUT"


def test_error_http_se_reporta():
    servicio, _ = _servicio(lambda r: httpx.Response(401, text="unauthorized"))

    with pytest.raises(EmqxError, match="401"):
        servicio.crear_credencial(CORREO, "x")


def test_actualizar_password():
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json={}))

    servicio.actualizar_password(CORREO, "Nueva#2026")

    assert peticiones[0].method == "PUT"
    assert json.loads(peticiones[0].content) == {"password": "Nueva#2026"}
