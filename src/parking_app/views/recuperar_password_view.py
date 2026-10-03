import flet as ft

from parking_app.core import theme
from parking_app.core.config import DOMINIOS_CORREO_PERMITIDOS, VIGENCIA_CODIGO_SEGUNDOS
from parking_app.viewmodels.alerta import Alerta
from parking_app.viewmodels.recuperar_password_viewmodel import (
    Paso,
    RecuperarPasswordViewModel,
)
from parking_app.viewmodels.registro_viewmodel import TEXTOS_REQUISITOS
from parking_app.views.components.formulario import (
    BannerAlerta,
    CampoFormulario,
    IndicadorPasos,
    ListaRequisitos,
    PantallaExito,
    actualizar,
    boton_principal,
    boton_secundario,
    icono_destacado,
    indicador_carga,
    texto_con_enlace,
)

RUTA = "/recuperar"

ALERTA_CODIGO_INVALIDO = Alerta(
    "El código no es válido o ya venció",
    "Revisa que lo hayas escrito igual que en el correo. "
    f"Si pasaron más de {VIGENCIA_CODIGO_SEGUNDOS // 60} minutos o ya lo usaste, "
    "solicita uno nuevo.",
)

TEXTOS_BOTON = {
    Paso.CORREO: "Enviar código",
    Paso.CODIGO: "Verificar código",
    Paso.NUEVA_PASSWORD: "Guardar contraseña",
}


def _titulo(texto: str) -> ft.Text:
    return ft.Text(texto, size=26, weight=ft.FontWeight.BOLD, color=theme.TEXTO)


def _subtitulo(texto: str) -> ft.Text:
    return ft.Text(texto, size=14, color=theme.TEXTO_SECUNDARIO)

# Clase representativa para construir las tres secciones de restablecimiento de contraseña desde el 
# paso del correo, ingreso del código de reestablecimiento el cambio de la contraseña.
class RecuperarPasswordView:
    """Flujo de 3 pasos: correo -> código -> nueva contraseña, y confirmación."""

    def __init__(self, vm: RecuperarPasswordViewModel) -> None:
        self._vm = vm
        self._indicador = IndicadorPasos(vm.total_pasos, self._on_regresar)
        self._banner = BannerAlerta()

        # Paso 1: correo
        self._correo = CampoFormulario(
            "Correo registrado",
            on_change=vm.set_correo,
            icono=ft.Icons.MAIL_OUTLINE,
            ayuda="Usa tu correo " + " o ".join(f"@{d}" for d in DOMINIOS_CORREO_PERMITIDOS),
            keyboard_type=ft.KeyboardType.EMAIL,
            autofill=ft.AutofillHint.EMAIL,
            on_submit=self._on_principal,
        )
        self._paso_correo = ft.Column(
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Row(controls=[
                    icono_destacado(ft.Icons.LOCK_OPEN_OUTLINED, theme.ICONO_AZUL_FONDO, theme.AZUL)
                ]),
                _titulo("Restablecer contraseña"),
                _subtitulo(
                    "Escribe el correo con el que te registraste. Te enviaremos un código "
                    "de verificación para crear una nueva contraseña."
                ),
                ft.Container(height=8),
                self._correo.control,
            ],
        )

        # Paso 2: código
        self._correo_destino = ft.TextSpan(
            style=ft.TextStyle(color=theme.TEXTO, weight=ft.FontWeight.W_700)
        )
        self._codigo = CampoFormulario(
            "Código de verificación",
            on_change=vm.set_codigo,
            keyboard_type=ft.KeyboardType.NUMBER,
            autofill=ft.AutofillHint.ONE_TIME_CODE,
            on_submit=self._on_principal,
        )
        self._codigo.campo.input_filter = ft.NumbersOnlyInputFilter()
        self._codigo.campo.text_style = ft.TextStyle(
            size=22, weight=ft.FontWeight.W_700, letter_spacing=8
        )
        self._tiempo = ft.TextSpan(
            style=ft.TextStyle(color=theme.NARANJA, weight=ft.FontWeight.W_700)
        )
        self._fila_vencimiento = ft.Row(
            spacing=6,
            controls=[
                ft.Icon(ft.Icons.SCHEDULE, size=14, color=theme.TEXTO_SECUNDARIO),
                ft.Text(
                    size=12,
                    color=theme.TEXTO_SECUNDARIO,
                    expand=True,
                    spans=[
                        ft.TextSpan("El código vence en "),
                        self._tiempo,
                        ft.TextSpan(" y solo puede usarse una vez."),
                    ],
                ),
            ],
        )
        self._banner_codigo = BannerAlerta(con_icono=False)
        self._banner_codigo.mostrar(ALERTA_CODIGO_INVALIDO)
        self._reenviar = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[texto_con_enlace("¿No te llegó?", "Reenviar código", self._on_reenviar)],
        )
        self._paso_codigo = ft.Column(
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Row(controls=[
                    icono_destacado(
                        ft.Icons.GPP_GOOD_OUTLINED, theme.ICONO_VERDE_FONDO, theme.VERDE_OSCURO
                    )
                ]),
                _titulo("Revisa tu correo"),
                ft.Text(
                    size=14,
                    color=theme.TEXTO_SECUNDARIO,
                    spans=[
                        ft.TextSpan("Enviamos un código de verificación a "),
                        self._correo_destino,
                        ft.TextSpan("."),
                    ],
                ),
                ft.Container(height=8),
                self._codigo.control,
                self._fila_vencimiento,
                self._banner_codigo.control,
                ft.Container(height=8),
                self._reenviar,
            ],
        )

        # Paso 3: nueva contraseña
        self._password = CampoFormulario(
            "Nueva contraseña",
            on_change=vm.set_password,
            icono=ft.Icons.LOCK_OUTLINE,
            password=True,
            autofill=ft.AutofillHint.NEW_PASSWORD,
        )
        self._requisitos = ListaRequisitos(list(TEXTOS_REQUISITOS.values()))
        self._confirmar = CampoFormulario(
            "Confirmar nueva contraseña",
            on_change=vm.set_confirmar_password,
            icono=ft.Icons.LOCK_OUTLINE,
            password=True,
            autofill=ft.AutofillHint.NEW_PASSWORD,
            on_submit=self._on_principal,
        )
        self._paso_password = ft.Column(
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                _titulo("Crea una nueva contraseña"),
                _subtitulo("Elige una contraseña que no hayas usado antes."),
                ft.Container(height=8),
                self._password.control,
                ft.Container(height=4),
                self._requisitos.control,
                ft.Container(height=4),
                self._confirmar.control,
            ],
        )

        self._boton = boton_principal(TEXTOS_BOTON[Paso.CORREO], self._on_principal)
        self._cargando = indicador_carga()
        self._boton_codigo_nuevo = boton_secundario(
            "Enviar un código nuevo", ft.Icons.REFRESH, self._on_reenviar
        )
        self._fila_codigo_nuevo = ft.Row(controls=[self._boton_codigo_nuevo])

        self._flujo = ft.Column(
            expand=True,
            spacing=24,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                self._indicador.control,
                ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=16,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    controls=[
                        self._paso_correo,
                        self._paso_codigo,
                        self._paso_password,
                        self._banner.control,
                    ],
                ),
                ft.Column(
                    spacing=12,
                    controls=[ft.Row(controls=[self._boton]), self._fila_codigo_nuevo],
                ),
                ft.Container(height=4),
            ],
        )
        self._pantalla_exito = PantallaExito(
            "Contraseña actualizada", "Ir a iniciar sesión", self._on_ir_a_login
        )
        self._pantalla_exito.detalle.value = "Ya puedes iniciar sesión con tu nueva contraseña."

        self.view = ft.View(
            route=RUTA,
            bgcolor=theme.FONDO,
            padding=ft.Padding.symmetric(horizontal=24, vertical=16),
            controls=[
                ft.SafeArea(
                    expand=True,
                    content=ft.Stack(
                        expand=True, controls=[self._flujo, self._pantalla_exito.control]
                    ),
                )
            ],
        )
        self._render()

    # --- Ciclo de vida (lo invoca el router) ---

    def montar(self) -> None:
        self._vm.add_listener(self._on_cambio)

    def desmontar(self) -> None:
        self._vm.remove_listener(self._on_cambio)
        self._vm.liberar()

    # --- ViewModel -> View ---

    def _on_cambio(self) -> None:
        self._render()
        actualizar(self.view)

    def _render(self) -> None:
        vm = self._vm
        completado = vm.paso == Paso.COMPLETADO
        self._flujo.visible = not completado
        self._pantalla_exito.control.visible = completado
        if completado:
            return

        self._indicador.sincronizar(vm.numero_paso)
        self._paso_correo.visible = vm.paso == Paso.CORREO
        self._paso_codigo.visible = vm.paso == Paso.CODIGO
        self._paso_password.visible = vm.paso == Paso.NUEVA_PASSWORD
        self._banner.mostrar(vm.alerta)

        self._correo.sincronizar(vm.correo, vm.error_correo)

        error_codigo = vm.mostrar_error_codigo
        self._correo_destino.text = vm.correo_normalizado
        self._codigo.sincronizar(vm.codigo, vm.error_codigo, error_codigo)
        self._codigo.campo.suffix_icon = (
            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=theme.NARANJA) if error_codigo else None
        )
        self._tiempo.text = vm.texto_vencimiento
        self._fila_vencimiento.visible = not error_codigo and vm.error_codigo is None
        self._banner_codigo.control.visible = error_codigo
        self._reenviar.visible = not error_codigo
        self._fila_codigo_nuevo.visible = vm.paso == Paso.CODIGO and error_codigo

        self._password.sincronizar(vm.password, vm.error_password)
        self._requisitos.sincronizar([cumplido for _, cumplido in vm.requisitos_password])
        self._confirmar.sincronizar(vm.confirmar_password, vm.error_confirmar)

        self._boton.disabled = not vm.puede_enviar
        self._boton.content = self._cargando if vm.cargando else TEXTOS_BOTON[vm.paso]
        self._boton_codigo_nuevo.disabled = not vm.puede_enviar

    # --- View -> ViewModel ---

    async def _on_principal(self, _e: ft.Event) -> None:
        acciones = {
            Paso.CORREO: self._vm.enviar_codigo,
            Paso.CODIGO: self._vm.verificar_codigo,
            Paso.NUEVA_PASSWORD: self._vm.guardar_password,
        }
        accion = acciones.get(self._vm.paso)
        if accion is not None:
            await accion()

    async def _on_reenviar(self, _e: ft.Event) -> None:
        await self._vm.reenviar_codigo()

    async def _on_regresar(self, _e: ft.Event) -> None:
        await self._vm.regresar()

    async def _on_ir_a_login(self, _e: ft.Event) -> None:
        await self._vm.ir_a_login()
