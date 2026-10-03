from parking_app.models.cajon_estacionamiento import CajonEstacionamiento, EstadoCajon
from parking_app.models.usuario import MedioTransporte, Rol, Usuario


def test_estado_cajon_acepta_formato_mqtt_y_de_bd():
    assert EstadoCajon.parse("no conectado") is EstadoCajon.NO_CONECTADO
    assert EstadoCajon.parse("no_conectado") is EstadoCajon.NO_CONECTADO
    assert EstadoCajon.NO_CONECTADO.valor_db == "no_conectado"


def test_cajon_desde_fila_de_bd():
    cajon = CajonEstacionamiento.from_row(
        {"id_cajon": 3, "etiqueta": "C3", "estado_actual": "no_conectado", "estado_actividad": True}
    )
    assert cajon.estado_actual is EstadoCajon.NO_CONECTADO


def test_usuario_to_row_deja_defaults_a_la_bd():
    usuario = Usuario(
        id_usuario="uid",
        nombre="Ana",
        apellido_paterno="Pérez",
        apellido_materno="",
        correo_institucional="ana@itsx.edu.mx",
        medio_transporte=MedioTransporte.MOTOCICLETA,
    )
    fila = usuario.to_row()
    assert fila["apellido_materno"] is None
    assert fila["medio_transporte"] == "motocicleta"
    assert not {"rol", "estado_cuenta", "fecha_registro", "intentos_fallidos"} & fila.keys()


def test_usuario_desde_fila_con_nulos():
    usuario = Usuario.from_row(
        {
            "id_usuario": "uid",
            "nombre": "Ana",
            "apellido_paterno": "Pérez",
            "apellido_materno": None,
            "correo_institucional": "ana@itsx.edu.mx",
            "medio_transporte": None,
            "rol": "administrador",
            "estado_cuenta": "activo",
            "fecha_registro": "2026-09-26T10:00:00+00:00",
        }
    )
    assert usuario.medio_transporte is None
    assert usuario.rol is Rol.ADMINISTRADOR
    assert usuario.nombre_completo == "Ana Pérez"
