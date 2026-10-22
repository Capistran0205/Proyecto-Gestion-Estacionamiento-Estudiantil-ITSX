import json

import httpx
import pytest

from parking_app.core.config import ConfigEmqx
from parking_app.services.emqx_admin_service import (
    EmqxAdminService,
    EmqxError,
    planear_migracion_acl,
)

TOPICO = "infraestructura/pruebaiot/prueba1"
TOPICO_SISTEMA = "infraestructura/pruebaiot/reserva1/+"
CORREO = "ana@itsx.edu.mx"


def _servicio(manejador, url="https://broker.ejemplo:18083"):
    peticiones = []

    def registrar(request: httpx.Request) -> httpx.Response:
        peticiones.append(request)
        return manejador(request)

    servicio = EmqxAdminService(
        config_factory=lambda: ConfigEmqx(url, "key", "secret"),
        topicos_factory=lambda: [TOPICO, TOPICO_SISTEMA],
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
    assert reglas == [
        {"topic": TOPICO, "permission": "allow", "action": "subscribe"},
        {"topic": TOPICO_SISTEMA, "permission": "allow", "action": "subscribe"},
        {"topic": "#", "permission": "deny", "action": "all"},
    ]


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


def test_listar_acl_recorre_todas_las_paginas():
    def manejador(r):
        pagina = int(r.url.params["page"])
        return httpx.Response(200, json={
            "data": [{"username": f"u{pagina}", "rules": []}],
            "meta": {"page": pagina, "hasnext": pagina < 3},
        })

    servicio, peticiones = _servicio(manejador)

    assert [e["username"] for e in servicio.listar_acl()] == ["u1", "u2", "u3"]
    assert len(peticiones) == 3


# --- Migración de ACL a reserva1/+ ---

def _regla(topico, permiso="allow", accion="subscribe"):
    return {"topic": topico, "permission": permiso, "action": accion}


ESTANDAR = [_regla(TOPICO), _regla(TOPICO_SISTEMA), _regla("#", "deny", "all")]
FASE_1 = [_regla(TOPICO), _regla("#", "deny", "all")]
ESP32 = [_regla(TOPICO, accion="publish"), _regla("#", "deny", "all")]


def test_migracion_estudiantes_reciben_el_acl_estandar():
    acl = [
        {"username": "ana@itsx.edu.mx", "rules": FASE_1},
        {"username": "luis@xalapa.tecnm.mx", "rules": FASE_1},
        # Ya migrado (la API agrega campos como qos/retain): no se toca.
        {"username": "eva@itsx.edu.mx", "rules": [{**r, "qos": [0, 1, 2]} for r in ESTANDAR]},
    ]
    cambios = planear_migracion_acl(acl, ESTANDAR, TOPICO_SISTEMA)
    assert cambios == [("ana@itsx.edu.mx", ESTANDAR), ("luis@xalapa.tecnm.mx", ESTANDAR)]


def test_migracion_esp32_conserva_sus_permisos_de_publicar():
    acl = [{"username": "Nodo_ESP32", "rules": ESP32}]
    assert planear_migracion_acl(acl, ESTANDAR, TOPICO_SISTEMA, ["Nodo_ESP32"]) == [
        ("Nodo_ESP32", [_regla(TOPICO_SISTEMA), *ESP32]),
    ]
    # Una segunda corrida no la vuelve a cambiar.
    migrada = [{"username": "Nodo_ESP32", "rules": [_regla(TOPICO_SISTEMA), *ESP32]}]
    assert planear_migracion_acl(migrada, ESTANDAR, TOPICO_SISTEMA, ["Nodo_ESP32"]) == []


def test_migracion_esp32_conserva_qos_y_retain_de_sus_reglas():
    # Formato real que devuelve la API de EMQX.
    publicar = {"action": "publish", "retain": "all", "permission": "allow",
                "topic": TOPICO, "qos": [0, 1, 2]}
    acl = [{"username": "AdminEstacionamientoPlacaESP32", "rules": [publicar]}]
    [(_, reglas)] = planear_migracion_acl(
        acl, ESTANDAR, TOPICO_SISTEMA, ["AdminEstacionamientoPlacaESP32"]
    )
    assert reglas == [_regla(TOPICO_SISTEMA), publicar]


def test_migracion_no_toca_otras_cuentas():
    acl = [{"username": "Alumno_Diego", "rules": ESP32}, {"username": "admin@gmail.com", "rules": []}]
    assert planear_migracion_acl(acl, ESTANDAR, TOPICO_SISTEMA) == []
