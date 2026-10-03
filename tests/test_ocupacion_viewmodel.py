import asyncio
import threading
from unittest.mock import MagicMock

from parking_app.models.cajon_estacionamiento import CajonEstacionamiento, EstadoCajon
from parking_app.models.evento_ocupacion import EventoOcupacion
from parking_app.services.auth_service import CredencialesMqtt
from parking_app.services.cajones_service import CajonesNoDisponiblesError
from parking_app.services.mqtt_service import EstadoConexion
from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel


class Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


def _snapshot(*estados):
    return [
        CajonEstacionamiento(id_cajon=i, etiqueta=f"C{i}", estado_actual=e)
        for i, e in enumerate(estados, start=1)
    ]


CREDENCIALES = CredencialesMqtt("ana@itsx.edu.mx", "Segura#2026")


def _auth(credenciales=True):
    """AuthService falso cuyo descartar_password_mqtt() sí borra la contraseña."""
    auth = MagicMock()
    auth.credenciales_mqtt = CREDENCIALES if credenciales else None

    def descartar():
        auth.credenciales_mqtt = None

    auth.descartar_password_mqtt.side_effect = descartar
    return auth


def _vm(snapshot=None, credenciales=True, timeout=60, auth=None, emqx=None):
    cajones, mqtt, reloj = MagicMock(), MagicMock(), Reloj()
    auth = auth or _auth(credenciales)
    cajones.obtener_estado_actual.return_value = snapshot or _snapshot(
        EstadoCajon.LIBRE, EstadoCajon.OCUPADO, EstadoCajon.LIBRE, EstadoCajon.NO_CONECTADO
    )
    vm = OcupacionViewModel(
        auth, cajones, mqtt, emqx or MagicMock(), timeout, MagicMock(), reloj=reloj
    )
    return vm, cajones, mqtt, reloj


def _callbacks(mqtt):
    kwargs = mqtt.conectar.call_args.kwargs
    return kwargs["al_recibir"], kwargs["al_cambiar_estado"]


def _evento(modulo, estado):
    return EventoOcupacion(id_modulo=modulo, estado=estado)


def _estados(vm):
    return [c.estado for c in vm.cajones]


def test_estado_inicial_antes_de_cargar():
    vm, _, _, _ = _vm()
    assert _estados(vm) == [EstadoCajon.NO_CONECTADO] * 4
    assert vm.texto_libres == "0 de 4 cajones libres"
    assert vm.texto_conexion == "Conectando…"
    assert vm.texto_actualizado == "Cargando estado del estacionamiento…"


def test_snapshot_y_conexion_con_credenciales_del_usuario():
    async def escenario():
        vm, _, mqtt, _ = _vm()
        await vm.iniciar()
        args = mqtt.conectar.call_args.args
        assert args == ("ana@itsx.edu.mx", "Segura#2026")
        assert _estados(vm)[:2] == [EstadoCajon.LIBRE, EstadoCajon.OCUPADO]
        assert vm.texto_libres == "2 de 4 cajones libres"
        assert vm.texto_actualizado == "Actualizado hace un momento"
        vm.detener()
        mqtt.desconectar.assert_called_once()

    asyncio.run(escenario())


def test_eventos_desde_el_hilo_de_paho_llegan_al_loop():
    async def escenario():
        vm, _, mqtt, _ = _vm()
        await vm.iniciar()
        al_recibir, al_cambiar_estado = _callbacks(mqtt)
        listener = MagicMock()
        vm.add_listener(listener)

        hilo = threading.Thread(
            target=lambda: (
                al_cambiar_estado(EstadoConexion.CONECTADO),
                al_recibir(_evento(4, EstadoCajon.OCUPADO)),
            )
        )
        hilo.start()
        hilo.join()
        await asyncio.sleep(0.05)

        assert vm.en_vivo and vm.texto_conexion == "En vivo"
        assert _estados(vm)[3] is EstadoCajon.OCUPADO
        assert listener.called
        vm.detener()

    asyncio.run(escenario())


def test_evento_previo_al_snapshot_no_se_pisa():
    async def escenario():
        vm, cajones, _, _ = _vm()

        def snapshot_con_evento_previo():
            # Un evento MQTT llega mientras la consulta a Supabase sigue en curso.
            vm._recibir_evento(_evento(1, EstadoCajon.RESERVADO))
            return _snapshot(*[EstadoCajon.LIBRE] * 4)

        cajones.obtener_estado_actual.side_effect = snapshot_con_evento_previo
        await vm.iniciar()
        assert _estados(vm)[0] is EstadoCajon.RESERVADO
        assert _estados(vm)[1] is EstadoCajon.LIBRE
        vm.detener()

    asyncio.run(escenario())


def test_nodo_sin_reportar_pasa_a_no_conectado():
    async def escenario():
        vm, _, _, reloj = _vm(timeout=60)
        await vm.iniciar()
        vm._cambiar_estado(EstadoConexion.CONECTADO)
        reloj.ahora += 30
        vm._recibir_evento(_evento(2, EstadoCajon.LIBRE))

        reloj.ahora += 31  # C1, C3, C4: 61 s sin reportar; C2: 31 s
        vm._revisar_nodos()

        assert _estados(vm) == [
            EstadoCajon.NO_CONECTADO,
            EstadoCajon.LIBRE,
            EstadoCajon.NO_CONECTADO,
            EstadoCajon.NO_CONECTADO,
        ]
        vm.detener()

    asyncio.run(escenario())


def test_sin_conexion_no_se_aplica_el_timeout():
    async def escenario():
        vm, _, _, reloj = _vm(timeout=60)
        await vm.iniciar()
        vm._cambiar_estado(EstadoConexion.CONECTADO)
        vm._cambiar_estado(EstadoConexion.RECONECTANDO)
        reloj.ahora += 600
        vm._revisar_nodos()
        assert _estados(vm)[0] is EstadoCajon.LIBRE

        vm._cambiar_estado(EstadoConexion.CONECTADO)  # nuevo plazo al reconectar
        vm._revisar_nodos()
        assert _estados(vm)[0] is EstadoCajon.LIBRE
        vm.detener()

    asyncio.run(escenario())


def test_falla_del_snapshot_no_bloquea_la_vista():
    async def escenario():
        vm, cajones, mqtt, _ = _vm()
        cajones.obtener_estado_actual.side_effect = CajonesNoDisponiblesError("x")
        await vm.iniciar()
        assert not vm.cargando
        assert vm.texto_actualizado == "Esperando datos de los sensores…"
        mqtt.conectar.assert_called_once()
        vm._recibir_evento(_evento(1, EstadoCajon.LIBRE))
        assert vm.libres == 1
        vm.detener()

    asyncio.run(escenario())


def test_sin_credenciales_mqtt():
    async def escenario():
        vm, _, mqtt, _ = _vm(credenciales=False)
        await vm.iniciar()
        mqtt.conectar.assert_not_called()
        assert vm.texto_conexion == "Sin acceso"
        assert vm.texto_actualizado == "No se pudo acceder al servidor de sensores"
        vm.detener()

    asyncio.run(escenario())


def test_texto_actualizado_en_el_tiempo():
    vm, _, _, reloj = _vm()
    vm._recibir_evento(_evento(1, EstadoCajon.LIBRE))
    reloj.ahora += 12
    assert vm.texto_actualizado == "Actualizado hace 12 segundos"
    reloj.ahora += 60
    assert vm.texto_actualizado == "Actualizado hace 1 minuto"
    reloj.ahora += 3600
    assert vm.texto_actualizado == "Actualizado hace más de una hora"


def test_al_conectar_se_descarta_la_password_sin_tocar_emqx():
    async def escenario():
        auth, emqx = _auth(), MagicMock()
        vm, _, _, _ = _vm(auth=auth, emqx=emqx)
        await vm.iniciar()

        vm._cambiar_estado(EstadoConexion.CONECTADO)

        assert auth.credenciales_mqtt is None
        emqx.crear_credencial.assert_not_called()
        vm.detener()

    asyncio.run(escenario())


def test_credencial_rechazada_se_resincroniza_con_emqx_y_reconecta():
    async def escenario():
        auth, emqx = _auth(), MagicMock()
        vm, _, mqtt, _ = _vm(auth=auth, emqx=emqx)
        await vm.iniciar()

        vm._cambiar_estado(EstadoConexion.CREDENCIALES_INVALIDAS)
        # Mientras se repara no se muestra "Sin acceso".
        assert vm.texto_conexion == "Conectando…"
        await vm._tarea_sincronizacion

        emqx.crear_credencial.assert_called_once_with("ana@itsx.edu.mx", "Segura#2026")
        assert mqtt.conectar.call_count == 2
        assert mqtt.conectar.call_args.args == ("ana@itsx.edu.mx", "Segura#2026")

        vm._cambiar_estado(EstadoConexion.CONECTADO)
        assert vm.texto_conexion == "En vivo"
        assert auth.credenciales_mqtt is None  # borrada tras el éxito
        vm.detener()

    asyncio.run(escenario())


def test_si_el_broker_la_rechaza_otra_vez_no_hay_segundo_intento():
    async def escenario():
        auth, emqx = _auth(), MagicMock()
        vm, _, mqtt, _ = _vm(auth=auth, emqx=emqx)
        await vm.iniciar()
        vm._cambiar_estado(EstadoConexion.CREDENCIALES_INVALIDAS)
        await vm._tarea_sincronizacion

        vm._cambiar_estado(EstadoConexion.CREDENCIALES_INVALIDAS)

        assert vm.texto_conexion == "Sin acceso"
        emqx.crear_credencial.assert_called_once()
        assert mqtt.conectar.call_count == 2
        assert auth.credenciales_mqtt is None
        vm.detener()

    asyncio.run(escenario())


def test_falla_de_emqx_al_resincronizar_muestra_sin_acceso():
    async def escenario():
        auth, emqx = _auth(), MagicMock()
        emqx.crear_credencial.side_effect = RuntimeError("EMQX caído")
        vm, _, mqtt, _ = _vm(auth=auth, emqx=emqx)
        await vm.iniciar()

        vm._cambiar_estado(EstadoConexion.CREDENCIALES_INVALIDAS)
        await vm._tarea_sincronizacion

        assert vm.texto_conexion == "Sin acceso"
        mqtt.conectar.assert_called_once()  # no se reconecta
        assert auth.credenciales_mqtt is None
        vm.detener()

    asyncio.run(escenario())


def test_rechazo_tras_haber_conectado_no_resincroniza_con_password_vieja():
    # P. ej. la contraseña se cambió desde otro teléfono y paho reconecta con la
    # anterior: reparar EMQX con ella lo haría retroceder.
    async def escenario():
        auth, emqx = _auth(), MagicMock()
        vm, _, _, _ = _vm(auth=auth, emqx=emqx)
        await vm.iniciar()
        vm._cambiar_estado(EstadoConexion.CONECTADO)
        vm._cambiar_estado(EstadoConexion.RECONECTANDO)

        vm._cambiar_estado(EstadoConexion.CREDENCIALES_INVALIDAS)

        assert vm.texto_conexion == "Sin acceso"
        emqx.crear_credencial.assert_not_called()
        vm.detener()

    asyncio.run(escenario())


def test_detener_cancela_la_resincronizacion_en_curso():
    async def escenario():
        vm, _, mqtt, _ = _vm()
        await vm.iniciar()
        vm._cambiar_estado(EstadoConexion.CREDENCIALES_INVALIDAS)
        tarea = vm._tarea_sincronizacion

        vm.detener()
        await asyncio.sleep(0)

        assert tarea.cancelled()
        mqtt.conectar.assert_called_once()

    asyncio.run(escenario())


def test_texto_libres_como_el_mockup():
    vm, _, _, _ = _vm()
    vm._recibir_evento(_evento(3, EstadoCajon.LIBRE))
    assert vm.texto_libres == "1 de 4 cajones libres"
