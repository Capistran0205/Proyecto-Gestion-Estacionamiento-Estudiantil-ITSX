import json
from datetime import datetime

import httpx
import pytest

from parking_app.models.reserva_cajon import EstadoReserva, ReservaCajon
from parking_app.services.almacen_reserva import AlmacenReserva
from parking_app.services.reservas_service import (
    ReservaError,
    ReservasNoDisponiblesError,
    ReservasService,
)

URL = "https://proyecto.supabase.co"

RESPUESTA_BLOQUEO = {
    "cajon": {"id_cajon": 3, "etiqueta": "C3", "estado_nuevo": "bloqueado"},
    "cajones_liberados": [],
    "bloqueado_hasta": "2026-10-06T16:22:00+00:00",
    "fecha_inicio": "2026-10-06T17:00:00+00:00",
    "fin_minimo": "2026-10-06T18:00:00+00:00",
    "fin_maximo": "2026-10-07T04:00:00+00:00",
    "reglas": {"cronometro_llegada_min": 60, "tolerancia_min": 20},
}
RESPUESTA_RESERVA = {
    "id_reserva": "5b1f6c1e-2c1d-4c39-9a51-6f0e8f2a3b4c",
    "codigo_qr": "a" * 32,
    "estado": "pendiente_llegada",
    "id_cajon": 3,
    "fecha_inicio": "2026-10-06T17:00:00+00:00",
    "fecha_fin": "2026-10-06T20:00:00+00:00",
    "cronometro": "2026-10-06T17:20:00+00:00",
}


def _servicio(manejador, token="jwt"):
    peticiones = []

    def registrar(request):
        peticiones.append(request)
        return manejador(request)

    servicio = ReservasService(
        token_factory=lambda: token,
        url_factory=lambda: (URL, "anon-key"),
        transporte=httpx.MockTransport(registrar),
    )
    return servicio, peticiones


def test_bloquear_envia_el_jwt_y_lee_el_horario_y_las_reglas():
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json=RESPUESTA_BLOQUEO))

    bloqueo = servicio.bloquear_cajon(3)

    [p] = peticiones
    assert str(p.url) == f"{URL}/functions/v1/bloquear-cajon"
    assert p.headers["authorization"] == "Bearer jwt"
    assert p.headers["apikey"] == "anon-key"
    assert json.loads(p.content) == {"id_cajon": 3}
    assert bloqueo.etiqueta == "C3"
    assert bloqueo.fecha_inicio == datetime.fromisoformat("2026-10-06T17:00:00+00:00")
    assert (bloqueo.minutos_llegada, bloqueo.minutos_tolerancia) == (60, 20)


def test_bloqueo_sin_reglas_del_backend():
    datos = {k: v for k, v in RESPUESTA_BLOQUEO.items() if k != "reglas"}
    servicio, _ = _servicio(lambda r: httpx.Response(200, json=datos))
    assert servicio.bloquear_cajon(3).minutos_llegada is None


def test_regla_de_negocio_conserva_codigo_y_mensaje():
    cuerpo = {"error": {"codigo": "CAJON_BLOQUEADO", "mensaje": "Otro estudiante está reservando."}}
    servicio, _ = _servicio(lambda r: httpx.Response(409, json=cuerpo))

    with pytest.raises(ReservaError) as e:
        servicio.bloquear_cajon(3)
    assert (e.value.codigo, e.value.mensaje, e.value.status) == (
        "CAJON_BLOQUEADO", "Otro estudiante está reservando.", 409,
    )


@pytest.mark.parametrize(
    "respuesta",
    [
        httpx.Response(500, json={"error": {"codigo": "ERROR_INTERNO", "mensaje": "x"}}),
        httpx.Response(502, text="<html>Bad gateway</html>"),
    ],
)
def test_fallas_del_servidor(respuesta):
    servicio, _ = _servicio(lambda r: respuesta)
    with pytest.raises(ReservasNoDisponiblesError):
        servicio.bloquear_cajon(3)


def test_jwt_rechazado_por_el_gateway():
    servicio, _ = _servicio(lambda r: httpx.Response(401, json={"msg": "Invalid JWT"}))
    with pytest.raises(ReservaError) as e:
        servicio.liberar_bloqueo(3)
    assert e.value.codigo == "NO_AUTENTICADO"


def test_sin_sesion_no_hace_la_peticion():
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json={}), token=None)
    with pytest.raises(ReservaError):
        servicio.bloquear_cajon(3)
    assert peticiones == []


def test_sin_red():
    def caido(_r):
        raise httpx.ConnectError("sin red")

    servicio, _ = _servicio(caido)
    with pytest.raises(ReservasNoDisponiblesError) as e:
        servicio.bloquear_cajon(3)
    assert e.value.sin_red


def test_funcion_no_desplegada_no_es_falta_de_red():
    cuerpo = {"code": "NOT_FOUND", "message": "Requested function was not found"}
    servicio, _ = _servicio(lambda r: httpx.Response(404, json=cuerpo))
    with pytest.raises(ReservasNoDisponiblesError) as e:
        servicio.bloquear_cajon(3)
    assert not e.value.sin_red


def test_crear_reserva_envia_las_fechas_y_lee_la_reserva():
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json=RESPUESTA_RESERVA))
    inicio = datetime.fromisoformat("2026-10-06T17:00:00+00:00")
    fin = datetime.fromisoformat("2026-10-06T20:00:00+00:00")

    reserva = servicio.crear_reserva(3, inicio, fin)

    assert json.loads(peticiones[0].content) == {
        "id_cajon": 3,
        "fecha_inicio": "2026-10-06T17:00:00+00:00",
        "fecha_fin": "2026-10-06T20:00:00+00:00",
    }
    assert reserva.estado is EstadoReserva.PENDIENTE_LLEGADA
    assert reserva.codigo_qr == "a" * 32


def test_liberar_sin_cajon_libera_todos():
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json={"cajones": []}))
    servicio.liberar_bloqueo()
    assert json.loads(peticiones[0].content) == {"id_cajon": None}


def test_crear_reserva_toma_la_etiqueta_del_cajon_recalculado():
    datos = {**RESPUESTA_RESERVA, "cajon": {"id_cajon": 3, "etiqueta": "C3"}}
    servicio, _ = _servicio(lambda r: httpx.Response(200, json=datos))
    reserva = servicio.crear_reserva(3, datetime.now(), datetime.now())
    assert reserva.etiqueta_cajon == "C3"


@pytest.mark.parametrize(
    ("metodo", "funcion"),
    [("cancelar_reserva", "cancelar-reserva"), ("confirmar_salida", "confirmar-salida")],
)
def test_acciones_sobre_la_reserva_envian_su_id(metodo, funcion):
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json={"estado": "x"}))
    getattr(servicio, metodo)("r1")
    [p] = peticiones
    assert str(p.url) == f"{URL}/functions/v1/{funcion}"
    assert json.loads(p.content) == {"id_reserva": "r1"}


def test_extender_devuelve_la_nueva_hora_de_fin():
    cuerpo = {"id_reserva": "r1", "id_cajon": 3, "fecha_fin": "2026-10-06T21:00:00+00:00"}
    servicio, _ = _servicio(lambda r: httpx.Response(200, json=cuerpo))
    assert servicio.extender_reserva("r1") == datetime.fromisoformat("2026-10-06T21:00:00+00:00")


def test_extension_rechazada_trae_el_motivo():
    cuerpo = {"error": {"codigo": "EXTENSION_NO_PERMITIDA", "mensaje": "Se excedería el horario."}}
    servicio, _ = _servicio(lambda r: httpx.Response(422, json=cuerpo))
    with pytest.raises(ReservaError) as e:
        servicio.extender_reserva("r1")
    assert e.value.codigo == "EXTENSION_NO_PERMITIDA"


def test_reserva_vigente_consulta_la_tabla_con_el_jwt():
    fila = {**RESPUESTA_RESERVA, "cajones": {"etiqueta": "C3"}}
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json=[fila]))

    reserva = servicio.reserva_vigente("uid-ana")

    [p] = peticiones
    assert p.method == "GET"
    assert p.url.path == "/rest/v1/reservas"
    assert p.url.params["id_usuario_estudiante"] == "eq.uid-ana"
    assert p.url.params["estado"] == "in.(pendiente_llegada,en_uso)"
    assert "cajones(etiqueta)" in p.url.params["select"]
    assert p.headers["authorization"] == "Bearer jwt"
    assert reserva.etiqueta == "C3"


def test_sin_reserva_vigente():
    servicio, _ = _servicio(lambda r: httpx.Response(200, json=[]))
    assert servicio.reserva_vigente("uid-ana") is None


def test_obtener_reserva_por_id_aunque_ya_haya_terminado():
    fila = {**RESPUESTA_RESERVA, "estado": "expirada"}
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json=[fila]))
    reserva = servicio.obtener_reserva(RESPUESTA_RESERVA["id_reserva"])
    assert peticiones[0].url.params["id_reserva"] == f"eq.{RESPUESTA_RESERVA['id_reserva']}"
    assert reserva.estado is EstadoReserva.EXPIRADA


def test_consulta_sin_red():
    def caido(_r):
        raise httpx.ReadTimeout("lento")

    servicio, _ = _servicio(caido)
    with pytest.raises(ReservasNoDisponiblesError) as e:
        servicio.obtener_reserva("r1")
    assert e.value.sin_red


# --- Administrador (Módulo C) ---

def test_reglas_vienen_de_la_edge_function():
    cuerpo = {"cronometro_llegada_min": 60, "tolerancia_min": 20}
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json=cuerpo))
    reglas = servicio.reglas()
    assert str(peticiones[0].url) == f"{URL}/functions/v1/reglas-reserva"
    assert (reglas.minutos_llegada, reglas.minutos_tolerancia) == (60, 20)


def test_confirmar_llegada_lee_cajon_y_estudiante():
    cuerpo = {
        "id_reserva": "5b1f6c1e-2c1d-4c39-9a51-6f0e8f2a3b4c", "id_usuario": "u", "id_cajon": 1,
        "fecha_llegada": "2026-10-06T17:05:00+00:00", "fecha_fin": "2026-10-06T20:00:00+00:00",
        "estudiante": {"nombre": "Ana", "apellido_paterno": "Pérez", "apellido_materno": None,
                       "medio_transporte": "vehiculo"},
        "cajon": {"id_cajon": 1, "etiqueta": "C1", "estado_nuevo": "reservado"},
    }
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json=cuerpo))
    llegada = servicio.confirmar_llegada("a" * 32)
    assert json.loads(peticiones[0].content) == {"codigo_qr": "a" * 32}
    assert (llegada.etiqueta, llegada.medio_transporte, llegada.nombre_estudiante) == (
        "C1", "vehiculo", "Ana Pérez")


def test_qr_rechazado_trae_el_motivo():
    cuerpo = {"error": {"codigo": "QR_USADO", "mensaje": "El código QR ya fue utilizado."}}
    servicio, _ = _servicio(lambda r: httpx.Response(409, json=cuerpo))
    with pytest.raises(ReservaError) as e:
        servicio.confirmar_llegada("a" * 32)
    assert e.value.codigo == "QR_USADO"


def test_reservas_activas_ordenadas_y_sin_codigos_qr():
    fila = {**RESPUESTA_RESERVA, "cajones": {"etiqueta": "C3"}}
    del fila["codigo_qr"]
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json=[fila]))
    [reserva] = servicio.reservas_activas()
    params = peticiones[0].url.params
    assert params["estado"] == "in.(pendiente_llegada,en_uso)"
    assert params["order"] == "fecha_usuario.asc"
    assert "codigo_qr" not in params["select"]
    assert reserva.etiqueta == "C3"


def test_datos_de_un_codigo_rechazado():
    fila = {**RESPUESTA_RESERVA, "estado": "cancelada"}
    servicio, peticiones = _servicio(lambda r: httpx.Response(200, json=[fila]))
    reserva = servicio.reserva_por_codigo("b" * 32)
    assert peticiones[0].url.params["codigo_qr"] == f"eq.{'b' * 32}"
    assert reserva.estado is EstadoReserva.CANCELADA


# --- Almacenamiento local (RNF-08) ---

def test_almacen_guarda_y_lee_la_reserva_del_mismo_estudiante(tmp_path):
    almacen = AlmacenReserva(tmp_path)
    reserva = ReservaCajon.from_dict(
        {**RESPUESTA_RESERVA, "etiqueta": "C3", "minutos_tolerancia": 20})

    almacen.guardar("uid-ana", reserva)

    assert almacen.leer("uid-ana") == reserva
    assert almacen.leer("uid-otro") is None  # otra cuenta en el mismo teléfono
    almacen.borrar()
    assert almacen.leer("uid-ana") is None


def test_almacen_ignora_un_archivo_danado(tmp_path):
    (tmp_path / "reserva_activa.json").write_text("{no es json", encoding="utf-8")
    assert AlmacenReserva(tmp_path).leer("uid-ana") is None
