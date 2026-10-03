from types import SimpleNamespace

from parking_app.core.config import ConfigMqtt
from parking_app.models.cajon_estacionamiento import EstadoCajon
from parking_app.services.mqtt_service import EstadoConexion, MqttService

TOPICO = "infraestructura/pruebaiot/prueba1"


class ClienteFalso:
    def __init__(self, client_id):
        self.client_id = client_id
        self.llamadas = []
        self.on_connect = self.on_disconnect = self.on_message = None

    def __getattr__(self, nombre):
        # Registra cualquier método de paho que se invoque.
        return lambda *a, **kw: self.llamadas.append((nombre, a, kw))


def _servicio(puerto=8883):
    clientes = []

    def fabrica(client_id):
        clientes.append(ClienteFalso(client_id))
        return clientes[-1]

    servicio = MqttService(
        config_factory=lambda: ConfigMqtt("broker.ejemplo", puerto, TOPICO),
        cliente_factory=fabrica,
    )
    eventos, estados = [], []
    servicio.conectar("ana@itsx.edu.mx", "Segura#2026", eventos.append, estados.append)
    return servicio, clientes[0], eventos, estados


def _rc(fallo=False, valor=0):
    return SimpleNamespace(is_failure=fallo, value=valor)


def _nombres(cliente):
    return [n for n, _, _ in cliente.llamadas]


def test_conecta_con_tls_y_credenciales_del_usuario():
    _, cliente, _, estados = _servicio()

    llamadas = {n: (a, kw) for n, a, kw in cliente.llamadas}
    assert llamadas["username_pw_set"][0] == ("ana@itsx.edu.mx", "Segura#2026")
    assert "tls_set" in llamadas
    assert llamadas["connect_async"][0] == ("broker.ejemplo", 8883)
    assert "loop_start" in llamadas
    assert estados == [EstadoConexion.CONECTANDO]


def test_sin_tls_en_puerto_1883():
    _, cliente, _, _ = _servicio(puerto=1883)
    assert "tls_set" not in _nombres(cliente)


def test_al_conectar_se_suscribe_al_topico():
    _, cliente, _, estados = _servicio()

    cliente.on_connect(cliente, None, None, _rc())

    assert ("subscribe", (TOPICO,), {"qos": 1}) in cliente.llamadas
    assert estados[-1] == EstadoConexion.CONECTADO


def test_credenciales_rechazadas_detiene_reintentos():
    _, cliente, _, estados = _servicio()

    cliente.on_connect(cliente, None, None, _rc(fallo=True, valor=134))
    cliente.on_disconnect(cliente, None, None, _rc())

    assert "disconnect" in _nombres(cliente)
    assert estados[-1] == EstadoConexion.CREDENCIALES_INVALIDAS


def test_perdida_de_conexion_reintenta():
    _, cliente, _, estados = _servicio()
    cliente.on_connect(cliente, None, None, _rc())

    cliente.on_disconnect(cliente, None, None, _rc(fallo=True, valor=7))

    assert estados[-1] == EstadoConexion.RECONECTANDO


def test_mensajes_validos_e_invalidos():
    _, cliente, eventos, _ = _servicio()

    for payload in (b'{"estado": "ocupado", "id_modulo": 3}', b"basura", b'{"id_modulo": 9}'):
        cliente.on_message(cliente, None, SimpleNamespace(payload=payload))

    assert len(eventos) == 1
    assert eventos[0].etiqueta_cajon == "C3"
    assert eventos[0].estado is EstadoCajon.OCUPADO


def test_desconectar():
    servicio, cliente, _, estados = _servicio()

    servicio.desconectar()
    cliente.on_disconnect(cliente, None, None, _rc())

    assert _nombres(cliente)[-2:] == ["disconnect", "loop_stop"]
    assert estados[-1] == EstadoConexion.DESCONECTADO
