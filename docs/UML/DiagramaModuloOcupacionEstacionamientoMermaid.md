```mermaid
classDiagram
direction LR
class Router { <<Controller>> -_ocupacion: OcupacionViewModel -_crear_ocupacion() Vista -_ocupacion_de_sesion() OcupacionViewModel -_detener_ocupacion() }
class OcupacionView {
  <<View>>
  -_vm: OcupacionViewModel
  -_pildora: PildoraConexion
  -_tarjetas: list
  -_actualizado: ft.Text
  +montar()
  +desmontar()
  -_on_cambio()
  -_render()
  -_al_tocar(etiqueta) Handler
  -_on_inicio(e)
}
class TarjetaCajon { <<View>> +control: ft.Container +/color_acento: str +/seleccionada: bool +sincronizar(estado, texto_estado, tocable, seleccionada, atenuada) }
class PildoraConexion { <<View>> +/texto: str +sincronizar(estado: EstadoConexion, texto) }
class InicioView { <<View>> -_pildora: PildoraConexion }
class OcupacionViewModel {
  <<ViewModel>>
  +estado_conexion: EstadoConexion
  +cargando: bool
  +error_snapshot: bool
  -_auth: AuthService
  -_cajones: CajonesService
  -_mqtt: MqttService
  -_emqx: EmqxAdminService
  -_timeout_nodo: int
  -_sensor: dict
  -_sistema: dict
  -_ultimo_reporte: dict
  -_tarea_reloj: Task
  +/cajones: list
  +/libres: int
  +/ocupados: int
  +/reservados: int
  +/porcentaje_ocupado: int
  +/nivel_disponibilidad: NivelDisponibilidad
  +/en_vivo: bool
  +/texto_conexion: str
  +/texto_actualizado: str
  +iniciar()
  +detener()
  +cajon(etiqueta) CajonVista
  +reservar(etiqueta)
  +reconectar_mqtt()
  -_cargar_snapshot()
  -_conectar_mqtt()
  -_recibir_evento(evento: EventoOcupacion)
  -_recibir_sistema(evento: EventoSistema)
  -_cambiar_estado(estado: EstadoConexion)
  -_sincronizar_y_reconectar(credenciales)
  -_revisar_nodos()
  -_tic()
}
class CajonVista { <<DTO>> +etiqueta: str +estado: EstadoCajon +texto_estado: str +id_cajon: int +/seleccionable: bool }
class NivelDisponibilidad { <<enumeration>> ALTA MEDIA LLENO SIN_DATOS }
class InicioViewModel { <<ViewModel>> +ocupacion: OcupacionViewModel }
class Observable { <<Core>> }
class CajonesService { <<Service>> -_cliente_factory: Callable +obtener_estado_actual() list }
class MqttService {
  <<Service>>
  -_cliente: mqtt.Client
  -_topico: str
  -_topico_sistema: str
  -_cerrando: bool
  +conectar(usuario, password, al_recibir, al_cambiar_estado, al_recibir_sistema)
  +desconectar()
  -_on_connect(...)
  -_on_disconnect(...)
  -_on_message(cliente, userdata, mensaje)
  -_notificar(estado)
}
class EstadoConexion { <<enumeration>> CONECTANDO CONECTADO RECONECTANDO CREDENCIALES_INVALIDAS DESCONECTADO }
class AuthService { <<Service>> +/credenciales_mqtt: CredencialesMqtt +descartar_password_mqtt() }
class EmqxAdminService { <<Service>> +crear_credencial(correo, contraseña) }
class CredencialesMqtt { <<DTO>> +usuario: str +password: str }
class CajonEstacionamiento { <<Entity>> +id_cajon: int +etiqueta: str +estado_actual: EstadoCajon +estado_actividad: bool +fecha_registro: datetime +from_row(row)$ CajonEstacionamiento }
class EventoOcupacion { <<Entity>> +id_modulo: int +estado: EstadoCajon +origen_evento: str +marca_tiempo: datetime +/etiqueta_cajon: str +from_payload(payload, origen)$ EventoOcupacion }
class EventoSistema { <<Entity>> +id_modulo: int +estado: EstadoSistema +marca_tiempo: datetime +from_payload(payload)$ EventoSistema }
class EstadoCajon { <<enumeration>> LIBRE OCUPADO RESERVADO BLOQUEADO NO_CONECTADO }
class EstadoSistema { <<enumeration>> BLOQUEADO RESERVADO LIBERADO }
class PayloadInvalidoError { <<Exception>> }
class CajonesNoDisponiblesError { <<Exception>> }
class ConfigMqtt { <<Config>> +host: str +port: int +topico_ocupacion: str +topico_sistema_base: str }
class supabase_client { <<Factory>> }
class theme { <<Utility>> +colores_estado(estado)$ ColoresEstado }

Router "1" *-- "0..1" OcupacionViewModel : único por sesión
Router ..> OcupacionView : create
Observable <|-- OcupacionViewModel
OcupacionView --> OcupacionViewModel : _vm / add_listener
OcupacionView *-- "4" TarjetaCajon
OcupacionView *-- PildoraConexion
InicioView *-- PildoraConexion
TarjetaCajon ..> theme
InicioViewModel o-- OcupacionViewModel : comparte snapshot y MQTT
OcupacionViewModel ..> CajonVista : create
OcupacionViewModel --> NivelDisponibilidad
OcupacionViewModel --> EstadoConexion
OcupacionViewModel --> CajonesService : snapshot inicial
OcupacionViewModel --> MqttService : suscripción
OcupacionViewModel --> AuthService : credenciales_mqtt
OcupacionViewModel --> EmqxAdminService : re-sincroniza credencial
CajonVista --> EstadoCajon
AuthService *-- CredencialesMqtt
CajonesService ..> supabase_client
CajonesService ..> CajonEstacionamiento : create
CajonesService ..> CajonesNoDisponiblesError : raise
MqttService ..> ConfigMqtt
MqttService ..> EventoOcupacion : create
MqttService ..> EventoSistema : create
MqttService ..> PayloadInvalidoError : descarta mensaje
CajonEstacionamiento --> EstadoCajon
EventoOcupacion --> EstadoCajon
EventoSistema --> EstadoSistema
```
