```mermaid
classDiagram
direction LR
class Router { <<Controller>> -_crear_perfil() Vista -_crear_cambiar_password() Vista -_perfil_actualizado() -_password_cambiada() }
class InicioView { <<View>> -_menu: MenuSandwich -_on_mi_perfil(e) }
class MenuSandwich { <<View>> +control: ft.NavigationDrawer +sincronizar(iniciales, nombre, numero_control, correo, cerrando_sesion) }
class InicioViewModel { <<ViewModel>> +ir_a_perfil() +cerrar_sesion() }
class PerfilView {
  <<View>>
  -_vm: PerfilViewModel
  -_banner_exito: BannerExito
  -_banner: BannerAlerta
  -_banner_reserva: BannerAlerta
  -_nombre: CampoFormulario
  -_apellido_paterno: CampoFormulario
  -_apellido_materno: CampoFormulario
  -_correo: CampoFormulario
  -_opciones_transporte: dict
  +montar()
  +desmontar()
  -_render()
  -_on_guardar(e)
  -_on_regresar(e)
  -_on_cambiar_password(e)
}
class CambiarPasswordView {
  <<View>>
  -_vm: CambiarPasswordViewModel
  -_actual: CampoFormulario
  -_nueva: CampoFormulario
  -_confirmar: CampoFormulario
  -_requisitos: ListaRequisitos
  -_pantalla_exito: PantallaExito
  +montar()
  +desmontar()
  -_render()
  -_on_actualizar(e)
  -_on_regresar(e)
}
class CampoFormulario { <<View>> }
class TarjetaOpcion { <<View>> }
class BannerExito { <<View>> +mostrar(mensaje) }
class ListaRequisitos { <<View>> }
class PantallaExito { <<View>> }
class PerfilViewModel {
  <<ViewModel>>
  +perfil_cargado: bool
  +nombre: str
  +apellido_paterno: str
  +apellido_materno: str
  +medio_transporte: MedioTransporte
  +errores: dict
  +cargando: bool
  +guardado: bool
  +aviso_reserva: Alerta
  -_auth: AuthService
  +/correo: str
  +/nombre_completo: str
  +/iniciales: str
  +/texto_rol: str
  +/alerta_reserva: Alerta
  +/mensaje_exito: str
  +/puede_guardar: bool
  +/hay_cambios: bool
  +error(campo) str
  +set_nombre(valor)
  +set_apellido_paterno(valor)
  +set_apellido_materno(valor)
  +set_medio_transporte(valor)
  +guardar()
  +regresar()
  +ir_a_cambiar_password()
  -_validar()
}
class CambiarPasswordViewModel {
  <<ViewModel>>
  +actual: str
  +nueva: str
  +confirmar: str
  +error_actual: str
  +error_nueva: str
  +error_confirmar: str
  +alerta: Alerta
  +cargando: bool
  +completado: bool
  -_auth: AuthService
  -_emqx: EmqxAdminService
  +/correo: str
  +/requisitos_password: list
  +/puede_enviar: bool
  +set_actual(valor)
  +set_nueva(valor)
  +set_confirmar(valor)
  +actualizar()
  +regresar()
  -_validar()
}
class Observable { <<Core>> }
class validadores { <<Utility>> +normalizar_nombre(valor)$ str +validar_nombre_apellido_persona(valor)$ str +estado_requisitos_password(p)$ dict }
class AuthService {
  <<Service>>
  +/usuario_actual: Usuario
  +/correo_actual: str
  +actualizar_perfil(nombre, apellido_paterno, apellido_materno, medio_transporte) Usuario
  +cambiar_password(actual, nueva, sincronizar_mqtt)
  -_actualizar_password_auth(nueva)
}
class EmqxAdminService { <<Service>> +crear_credencial(correo, contraseña) }
class CredencialesMqtt { <<DTO>> +usuario: str +password: str }
class Usuario { <<Entity>> +nombre: str +apellido_paterno: str +apellido_materno: str +medio_transporte: MedioTransporte +rol: Rol +/nombre_completo: str +/iniciales: str }
class MedioTransporte { <<enumeration>> MOTOCICLETA VEHICULO }
class AuthServiceError { <<Exception>> }
class MedioTransporteBloqueadoError { <<Exception>> }
class PasswordActualIncorrectaError { <<Exception>> +intentos_restantes: int }
class CambioPasswordRevertidoError { <<Exception>> }
class PasswordRepetidaError { <<Exception>> }
class SinSesionError { <<Exception>> }

Router ..> PerfilViewModel : create
Router ..> CambiarPasswordViewModel : create
InicioView *-- MenuSandwich
InicioView --> InicioViewModel
InicioViewModel ..> Router : al_ir_a_perfil()
Observable <|-- PerfilViewModel
Observable <|-- CambiarPasswordViewModel
PerfilView --> PerfilViewModel : _vm / add_listener
CambiarPasswordView --> CambiarPasswordViewModel : _vm / add_listener
PerfilView *-- "4" CampoFormulario
PerfilView *-- "2" TarjetaOpcion
PerfilView *-- BannerExito
CambiarPasswordView *-- "3" CampoFormulario
CambiarPasswordView *-- ListaRequisitos
CambiarPasswordView *-- PantallaExito
PerfilViewModel ..> CambiarPasswordViewModel : navega
PerfilViewModel --> AuthService : _auth
PerfilViewModel ..> validadores
CambiarPasswordViewModel --> AuthService : _auth
CambiarPasswordViewModel --> EmqxAdminService : _emqx
CambiarPasswordViewModel ..> validadores
AuthService ..> EmqxAdminService : sincronizar_mqtt = crear_credencial
AuthService --> Usuario
AuthService *-- CredencialesMqtt
Usuario --> MedioTransporte
AuthServiceError <|-- MedioTransporteBloqueadoError
AuthServiceError <|-- PasswordActualIncorrectaError
AuthServiceError <|-- CambioPasswordRevertidoError
AuthServiceError <|-- PasswordRepetidaError
AuthServiceError <|-- SinSesionError
```
