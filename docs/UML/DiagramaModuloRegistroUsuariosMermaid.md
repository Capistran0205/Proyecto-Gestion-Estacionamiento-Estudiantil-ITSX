```mermaid
classDiagram
direction LR
class RegistroView {
  <<View>>
  -_vm: RegistroViewModel
  -_nombre: CampoFormulario
  -_apellido_paterno: CampoFormulario
  -_apellido_materno: CampoFormulario
  -_correo: CampoFormulario
  -_password: CampoFormulario
  -_confirmar: CampoFormulario
  -_opciones_transporte: dict
  -_requisitos: ListaRequisitos
  -_pantalla_exito: PantallaExito
  -_banner_duplicado: BannerAlerta
  +montar()
  +desmontar()
  -_render()
  -_on_crear_cuenta(e)
  -_on_ir_a_login(e)
  -_on_ir_a_recuperar(e)
}
class CampoFormulario { <<View>> +sincronizar(valor, error, resaltado) }
class TarjetaOpcion { <<View>> +/seleccionada: bool +sincronizar(seleccionada, resaltada) }
class ListaRequisitos { <<View>> +sincronizar(cumplidos) }
class PantallaExito { <<View>> +detalle: ft.Text }
class BannerAlerta { <<View>> +mostrar(alerta) }
class RegistroViewModel {
  <<ViewModel>>
  +nombre: str
  +apellido_paterno: str
  +apellido_materno: str
  +medio_transporte: MedioTransporte
  +correo: str
  +password: str
  +confirmar_password: str
  +errores: dict
  +correo_duplicado: bool
  +cargando: bool
  +resultado: ResultadoRegistro
  -_auth: AuthService
  -_emqx: EmqxAdminService
  +/alerta: Alerta
  +/requisitos_password: list
  +/puede_enviar: bool
  +/registro_completado: bool
  +error(campo) str
  +set_nombre(valor)
  +set_apellido_paterno(valor)
  +set_apellido_materno(valor)
  +set_medio_transporte(valor)
  +set_correo(valor)
  +set_password(valor)
  +set_confirmar_password(valor)
  +crear_cuenta()
  +ir_a_login()
  +ir_a_recuperar()
  -_aprovisionar_mqtt(correo)
  -_validar()
}
class Observable { <<Core>> }
class validadores {
  <<Utility>>
  +validar_correo_institucional(correo)$ str
  +estado_requisitos_password(password)$ dict
  +normalizar_nombre(valor)$ str
  +validar_nombre_apellido_persona(valor)$ str
}
class AuthService { <<Service>> +registrar(usuario, contraseña) ResultadoRegistro }
class ResultadoRegistro { <<DTO>> +usuario: Usuario +requiere_confirmacion: bool }
class EmqxAdminService {
  <<Service>>
  -_config_factory: Callable
  -_topicos_factory: Callable
  -_timeout: float
  +crear_credencial(correo, contraseña)
  +reglas_estudiante() list
  -_asignar_acl(cliente, usuario, reglas)
  -_cliente() httpx.Client
}
class ConfigEmqx { <<Config>> +api_url: str +api_key: str +api_secret: str }
class EmqxError { <<Exception>> }
class Usuario {
  <<Entity>>
  +id_usuario: str
  +nombre: str
  +apellido_paterno: str
  +apellido_materno: str
  +correo_institucional: str
  +medio_transporte: MedioTransporte
  +rol: Rol
  +estado_cuenta: EstadoCuenta
  +to_row() dict
}
class MedioTransporte { <<enumeration>> MOTOCICLETA VEHICULO }
class Rol { <<enumeration>> ESTUDIANTE ADMINISTRADOR }
class EstadoCuenta { <<enumeration>> ACTIVO INACTIVO }
class AuthServiceError { <<Exception>> }
class CorreoYaRegistradoError { <<Exception>> }
class LimiteCorreosError { <<Exception>> }
class PasswordDebilError { <<Exception>> +razones: list }
class DatosInvalidosError { <<Exception>> +campo: str }

Observable <|-- RegistroViewModel
RegistroView --> RegistroViewModel : _vm / add_listener
RegistroView *-- "6" CampoFormulario
RegistroView *-- "2" TarjetaOpcion
RegistroView *-- ListaRequisitos
RegistroView *-- PantallaExito
RegistroView *-- "2" BannerAlerta
RegistroViewModel --> AuthService : _auth
RegistroViewModel --> EmqxAdminService : _emqx
RegistroViewModel ..> Usuario : create
RegistroViewModel --> ResultadoRegistro
RegistroViewModel ..> validadores
RegistroViewModel ..> EmqxError : except, solo log
ResultadoRegistro *-- Usuario
EmqxAdminService ..> ConfigEmqx
Usuario --> MedioTransporte
Usuario --> Rol
Usuario --> EstadoCuenta
AuthServiceError <|-- CorreoYaRegistradoError
AuthServiceError <|-- LimiteCorreosError
AuthServiceError <|-- PasswordDebilError
AuthServiceError <|-- DatosInvalidosError
```
