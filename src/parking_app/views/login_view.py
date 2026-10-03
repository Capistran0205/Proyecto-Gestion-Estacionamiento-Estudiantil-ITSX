import flet as ft

from parking_app.core import theme
from parking_app.core.config import DOMINIOS_CORREO_PERMITIDOS
from parking_app.viewmodels.login_viewmodel import LoginViewModel
from parking_app.views.components.formulario import (
    BannerAlerta,
    CampoFormulario,
    actualizar,
    boton_principal,
    encabezado,
    enlace,
    indicador_carga,
    texto_con_enlace,
)

RUTA = "/login"

# Clase que construye la pantalla, se suscribe o desuscribe al ViewModel para mandar los eventos, además, repinta la interfaz
class LoginView:
    """Pantalla de inicio de sesión. Solo pinta el estado del ViewModel."""

    def __init__(self, vm: LoginViewModel) -> None:
        self._vm = vm

        self._banner = BannerAlerta()
        self._correo = CampoFormulario(
            "Correo institucional",
            on_change=vm.set_correo,
            icono=ft.Icons.MAIL_OUTLINE,
            ayuda="Usa tu correo " + " o ".join(f"@{d}" for d in DOMINIOS_CORREO_PERMITIDOS),
            keyboard_type=ft.KeyboardType.EMAIL,
            autofill=ft.AutofillHint.EMAIL,
        )
        self._password = CampoFormulario(
            "Contraseña",
            on_change=vm.set_password,
            icono=ft.Icons.LOCK_OUTLINE,
            password=True,
            autofill=ft.AutofillHint.PASSWORD,
            on_submit=self._on_iniciar_sesion,
        )
        self._boton = boton_principal("Iniciar sesión", self._on_iniciar_sesion)
        self._cargando = indicador_carga()

        formulario = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=20,
            controls=[
                ft.Container(height=24),
                encabezado("Estacionamiento Alumnos", "Inicia sesión con tu cuenta institucional"),
                ft.Container(height=4),
                self._banner.control,
                self._correo.control,
                self._password.control,
                ft.Row(
                    alignment=ft.MainAxisAlignment.END,
                    controls=[enlace("¿Olvidaste tu contraseña?", self._on_recuperar)],
                ),
            ],
        )
        pie = ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=18,
            controls=[
                ft.Row(controls=[self._boton]),
                texto_con_enlace("¿No tienes cuenta?", "Regístrate", self._on_registro),
                ft.Container(height=8),
            ],
        )

        self.view = ft.View(
            route=RUTA,
            bgcolor=theme.FONDO,
            padding=ft.Padding.symmetric(horizontal=24, vertical=16),
            controls=[
                ft.SafeArea(expand=True, content=ft.Column(expand=True, controls=[formulario, pie]))
            ],
        )
        self._render()

    # --- Ciclo de vida (lo invoca el router) ---
    # Se suscribe al ViewModel
    def montar(self) -> None:
        self._vm.add_listener(self._on_cambio)
    # Se desuscribe del ViewModel
    def desmontar(self) -> None:
        self._vm.remove_listener(self._on_cambio)
        self._vm.liberar()

    # --- ViewModel -> View ---

    def _on_cambio(self) -> None:
        self._render()
        actualizar(self.view)

    def _render(self) -> None:
        vm = self._vm
        self._banner.mostrar(vm.alerta)
        self._correo.sincronizar(vm.correo, vm.error_correo, vm.resaltar_campos)
        self._password.sincronizar(vm.password, vm.error_password, vm.resaltar_campos)

        self._boton.disabled = not vm.puede_enviar
        self._boton.content = self._cargando if vm.cargando else "Iniciar sesión"
        # Bloqueado: el botón se atenúa pero conserva el color de la marca.
        self._boton.opacity = 0.5 if vm.bloqueado else 1.0

    # --- View -> ViewModel ---

    async def _on_iniciar_sesion(self, _e: ft.Event) -> None:
        await self._vm.iniciar_sesion()

    async def _on_recuperar(self, _e: ft.Event) -> None:
        await self._vm.ir_a_recuperar()

    async def _on_registro(self, _e: ft.Event) -> None:
        await self._vm.ir_a_registro()
