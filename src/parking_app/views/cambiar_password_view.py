import logging

import flet as ft

from parking_app.core import theme
from parking_app.viewmodels.cambiar_password_viewmodel import CambiarPasswordViewModel
from parking_app.viewmodels.registro_viewmodel import TEXTOS_REQUISITOS
from parking_app.views.components.formulario import (
    BannerAlerta,
    CampoFormulario,
    ListaRequisitos,
    PantallaExito,
    actualizar,
    barra_titulo,
    boton_principal,
    indicador_carga,
    nota_informativa,
)

logger = logging.getLogger(__name__)

RUTA = "/perfil/password"


def _campo_password(texto: str, on_change, autofill: ft.AutofillHint, on_submit=None) -> CampoFormulario:
    return CampoFormulario(
        texto,
        on_change=on_change,
        icono=ft.Icons.LOCK_OUTLINE,
        password=True,
        autofill=autofill,
        on_submit=on_submit,
    )


# Clase representativa de "Cambiar contraseña" (formulario) y "Contraseña actualizada" (éxito).
class CambiarPasswordView:
    def __init__(self, vm: CambiarPasswordViewModel) -> None:
        self._vm = vm

        self._banner = BannerAlerta()
        self._actual = _campo_password(
            "Contraseña actual", vm.set_actual, ft.AutofillHint.PASSWORD
        )
        self._nueva = _campo_password(
            "Nueva contraseña", vm.set_nueva, ft.AutofillHint.NEW_PASSWORD
        )
        self._requisitos = ListaRequisitos(
            list(TEXTOS_REQUISITOS.values()), titulo="Tu nueva contraseña debe tener:"
        )
        self._confirmar = _campo_password(
            "Confirmar nueva contraseña",
            vm.set_confirmar,
            ft.AutofillHint.NEW_PASSWORD,
            on_submit=self._on_actualizar,
        )
        self._boton = boton_principal("Actualizar contraseña", self._on_actualizar)
        self._cargando = indicador_carga()

        self._formulario = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=20,
            controls=[
                ft.Column(
                    spacing=16,
                    controls=[
                        barra_titulo("Cambiar contraseña", self._on_regresar),
                        ft.Text(
                            "Por seguridad, escribe tu contraseña actual antes de crear una nueva.",
                            size=14,
                            color=theme.TEXTO_SECUNDARIO,
                        ),
                    ],
                ),
                self._banner.control,
                self._actual.control,
                self._nueva.control,
                self._requisitos.control,
                self._confirmar.control,
                nota_informativa(
                    ft.Icons.MAIL_OUTLINE,
                    "Cuando cambies tu contraseña te enviaremos un aviso a tu correo institucional.",
                ),
                ft.Row(controls=[self._boton]),
                ft.Container(height=8),
            ],
        )

        self._pantalla_exito = PantallaExito(
            "Contraseña actualizada", "Volver a mi perfil", self._on_regresar
        )
        self._exito = self._pantalla_exito.control

        self.view = ft.View(
            route=RUTA,
            bgcolor=theme.FONDO,
            padding=ft.Padding.symmetric(horizontal=24, vertical=16),
            controls=[
                ft.SafeArea(
                    expand=True,
                    content=ft.Stack(expand=True, controls=[self._formulario, self._exito]),
                )
            ],
        )
        self._render()

    # --- Ciclo de vida (lo invoca el router) ---

    def montar(self) -> None:
        self._vm.add_listener(self._on_cambio)

    def desmontar(self) -> None:
        self._vm.remove_listener(self._on_cambio)

    # --- ViewModel -> View ---

    def _on_cambio(self) -> None:
        self._render()
        actualizar(self.view)

    def _render(self) -> None:
        vm = self._vm
        self._formulario.visible = not vm.completado
        self._exito.visible = vm.completado
        if vm.completado:
            # "Enviamos un aviso a <correo> como medida de seguridad." con el correo resaltado.
            self._pantalla_exito.detalle.spans = [
                ft.TextSpan("Enviamos un aviso a "),
                ft.TextSpan(
                    vm.correo,
                    style=ft.TextStyle(weight=ft.FontWeight.BOLD, color=theme.TEXTO),
                ),
                ft.TextSpan(" como medida de seguridad."),
            ]
            return

        self._banner.mostrar(vm.alerta)
        self._actual.sincronizar(vm.actual, vm.error_actual)
        self._nueva.sincronizar(vm.nueva, vm.error_nueva)
        self._requisitos.sincronizar([cumplido for _, cumplido in vm.requisitos_password])
        self._confirmar.sincronizar(vm.confirmar, vm.error_confirmar)

        self._boton.disabled = not vm.puede_enviar
        self._boton.content = self._cargando if vm.cargando else "Actualizar contraseña"

    # --- View -> ViewModel ---

    async def _on_actualizar(self, _e: ft.Event) -> None:
        await self._vm.actualizar()
        if self._vm.alerta is not None:
            try:
                await self._formulario.scroll_to(offset=0, duration=300)
            except RuntimeError:
                logger.debug("Formulario sin montar; no se desplaza")

    async def _on_regresar(self, _e: ft.Event) -> None:
        await self._vm.regresar()
