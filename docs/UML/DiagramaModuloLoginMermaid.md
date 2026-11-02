```mermaid
classDiagram
direction LR
class Router { <<Controller>> +ir(ruta) -_mostrar(ruta) -_crear_login() Vista }
class Vista { <<Interface>> +view: ft.View +montar() +desmontar() }
class LoginView {
  <<View>>
  +view: ft.View
  -_vm: LoginViewModel
  -_banner: BannerAlerta
  -_correo: CampoFormulario
  -_password: CampoFormulario
  +montar()
  +desmontar()
  -_on_cambio()
  -_render()
  -_on_iniciar_sesion(e)
  -_on_recuperar(e)
  -_on_registro(e)
}
class CampoFormulario { <<View>> +campo: ft.TextField +error: MensajeError +sincronizar(valor, error, resaltado) }
class BannerAlerta { <<View>> +/titulo: str +mostrar(alerta: Alerta) }
class LoginViewModel {
  <<ViewModel>>
  +correo: str
  +password: str
  +error_correo: str
  +error_password: str
  +cargando: bool
  +segundos_bloqueo: int
  -_auth: AuthService
  -_al_iniciar_sesion: Navegar
  -_al_ir_a_registro: Navegar
  -_al_ir_a_recuperar: Navegar
  -_cuenta_regresiva: Task
  +/bloqueado: bool
  +/puede_enviar: bool
  +/alerta: Alerta
  +/resaltar_campos: bool
  +set_correo(valor: str)
  +set_password(valor: str)
  +iniciar_sesion()
  +ir_a_registro()
  +ir_a_recuperar()
  +liberar()
  -_iniciar_cuenta_regresiva(segundos: int)
  -_contar(correo_bloqueado: str)
}
class Alerta { <<DTO>> +titulo: str +detalle: str }
class Observable { <<Core>> +add_listener(l) +remove_listener(l) +notify_listeners() }
class validadores { <<Utility>> +validar_correo_institucional(correo)$ str +normalizar_correo(correo)$ str }
class AuthService {
  <<Service>>
  -_intentos: ControlIntentos
  -_sesion: Sesion
  -_usuario: Usuario
  -_credenciales_mqtt: CredencialesMqtt
  +/hay_sesion_activa: bool
  +/usuario_actual: Usuario
  +/credenciales_mqtt: CredencialesMqtt
  +segundos_bloqueo_restantes(correo) int
  +iniciar_sesion(correo, contraseña) Sesion
  +cerrar_sesion()
  -_registrar_sesion(sesion)
  -_obtener_usuario(id_usuario) Usuario
}
class ControlIntentos {
  <<Service>>
  -_max: int
  -_bloqueo: int
  -_fallos: dict
  -_bloqueado_hasta: dict
  +segundos_restantes(correo) int
  +registrar_fallo(correo) int
  +reiniciar(correo)
}
class CredencialesMqtt { <<DTO>> +usuario: str +password: str }
class Sesion {
  <<Entity>>
  +id_sesion: str
  +id_usuario: str
  +token: str
  +fecha_acceso: datetime
  +fecha_cierre_sesion: datetime
  +estado: EstadoSesion
  +/activa: bool
  +/huella_token: str
  +to_row() dict
}
class Usuario {
  <<Entity>>
  +id_usuario: str
  +nombre: str
  +correo_institucional: str
  +rol: Rol
  +estado_cuenta: EstadoCuenta
  +intentos_fallidos: int
  +tiempo_bloqueo_acceso: datetime
  +/activo: bool
  +from_row(row)$ Usuario
}
class EstadoSesion { <<enumeration>> ACTIVO INACTIVO }
class supabase_client { <<Factory>> +get_supabase()$ Client }
class AuthServiceError { <<Exception>> }
class CredencialesInvalidasError { <<Exception>> +intentos_restantes: int }
class CuentaBloqueadaError { <<Exception>> +segundos_restantes: int }
class CuentaInactivaError { <<Exception>> }
class CorreoNoConfirmadoError { <<Exception>> }
class ServicioNoDisponibleError { <<Exception>> }

Router ..> LoginViewModel : create
Router *-- Vista
Router --> AuthService : protege RUTAS_PROTEGIDAS
Vista <|.. LoginView
Observable <|-- LoginViewModel
LoginView --> LoginViewModel : _vm / add_listener
LoginView *-- "2" CampoFormulario
LoginView *-- BannerAlerta
LoginViewModel --> AuthService : _auth
LoginViewModel ..> Alerta
LoginViewModel ..> validadores
AuthService *-- ControlIntentos
AuthService --> Sesion
AuthService --> Usuario
AuthService *-- CredencialesMqtt
AuthService ..> supabase_client
Sesion --> EstadoSesion
AuthServiceError <|-- CredencialesInvalidasError
AuthServiceError <|-- CuentaBloqueadaError
AuthServiceError <|-- CuentaInactivaError
AuthServiceError <|-- CorreoNoConfirmadoError
AuthServiceError <|-- ServicioNoDisponibleError
```
