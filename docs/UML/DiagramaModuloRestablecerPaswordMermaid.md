```mermaid
classDiagram
direction LR
class Router { <<Controller>> -_crear_recuperar() Vista }
class RecuperarPasswordView {
  <<View>>
  -_vm: RecuperarPasswordViewModel
  -_indicador: IndicadorPasos
  -_correo: CampoFormulario
  -_codigo: CampoFormulario
  -_password: CampoFormulario
  -_confirmar: CampoFormulario
  -_requisitos: ListaRequisitos
  -_banner: BannerAlerta
  -_banner_codigo: BannerAlerta
  -_pantalla_exito: PantallaExito
  +montar()
  +desmontar()
  -_render()
  -_on_principal(e)
  -_on_reenviar(e)
  -_on_regresar(e)
  -_on_ir_a_login(e)
}
class IndicadorPasos { <<View>> +/texto: str +sincronizar(paso: int) }
class CampoFormulario { <<View>> }
class ListaRequisitos { <<View>> }
class BannerAlerta { <<View>> }
class PantallaExito { <<View>> }
class Paso { <<enumeration>> CORREO CODIGO NUEVA_PASSWORD COMPLETADO }
class RecuperarPasswordViewModel {
  <<ViewModel>>
  +paso: Paso
  +correo: str
  +codigo: str
  +password: str
  +confirmar_password: str
  +error_correo: str
  +error_codigo: str
  +codigo_invalido: bool
  +error_password: str
  +error_confirmar: str
  +alerta: Alerta
  +cargando: bool
  -_auth: AuthService
  -_emqx: EmqxAdminService
  -_reloj: Callable
  -_vence_en: float
  -_temporizador: Task
  -_codigo_verificado: bool
  +/numero_paso: int
  +/segundos_restantes: int
  +/texto_vencimiento: str
  +/codigo_vencido: bool
  +/requisitos_password: list
  +/puede_enviar: bool
  +set_correo(valor)
  +set_codigo(valor)
  +set_password(valor)
  +set_confirmar_password(valor)
  +enviar_codigo()
  +reenviar_codigo()
  +verificar_codigo()
  +guardar_password()
  +regresar()
  +ir_a_login()
  +liberar()
  -_solicitar_codigo() bool
  -_sincronizar_mqtt()
  -_iniciar_temporizador()
  -_detener_temporizador()
  -_contar()
}
class Alerta { <<DTO>> }
class Observable { <<Core>> }
class config { <<Config>> +VIGENCIA_CODIGO_SEGUNDOS: int$ }
class validadores { <<Utility>> +validar_correo_institucional(c)$ str +normalizar_correo(c)$ str +estado_requisitos_password(p)$ dict }
class AuthService {
  <<Service>>
  +solicitar_restablecimiento(correo)
  +verificar_codigo_recuperacion(correo, codigo)
  +confirmar_nueva_password(nueva)
  +cancelar_recuperacion()
}
class EmqxAdminService { <<Service>> +crear_credencial(correo, contraseña) }
class supabase_client { <<Factory>> +get_supabase()$ Client }
class AuthServiceError { <<Exception>> }
class CodigoInvalidoError { <<Exception>> }
class LimiteCorreosError { <<Exception>> }
class PasswordDebilError { <<Exception>> }
class PasswordRepetidaError { <<Exception>> }
class SinSesionError { <<Exception>> }

Router ..> RecuperarPasswordViewModel : create
Observable <|-- RecuperarPasswordViewModel
RecuperarPasswordView --> RecuperarPasswordViewModel : _vm / add_listener
RecuperarPasswordView *-- IndicadorPasos
RecuperarPasswordView *-- "4" CampoFormulario
RecuperarPasswordView *-- ListaRequisitos
RecuperarPasswordView *-- "2" BannerAlerta
RecuperarPasswordView *-- PantallaExito
RecuperarPasswordViewModel --> Paso
RecuperarPasswordViewModel --> AuthService : _auth
RecuperarPasswordViewModel --> EmqxAdminService : _sincronizar_mqtt()
RecuperarPasswordViewModel ..> validadores
RecuperarPasswordViewModel ..> config
RecuperarPasswordViewModel ..> Alerta
AuthService ..> supabase_client
AuthServiceError <|-- CodigoInvalidoError
AuthServiceError <|-- LimiteCorreosError
AuthServiceError <|-- PasswordDebilError
AuthServiceError <|-- PasswordRepetidaError
AuthServiceError <|-- SinSesionError
```
