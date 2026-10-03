import logging

import flet as ft

from parking_app.core import theme
from parking_app.core.config import DOMINIOS_CORREO_PERMITIDOS
from parking_app.models.usuario import MedioTransporte
from parking_app.viewmodels.alerta import Alerta
from parking_app.viewmodels.registro_viewmodel import TEXTOS_REQUISITOS, RegistroViewModel
from parking_app.views.components.formulario import (
    BannerAlerta,
    CampoFormulario,
    ListaRequisitos,
    MensajeError,
    PantallaExito,
    TarjetaOpcion,
    actualizar,
    boton_principal,
    encabezado_pagina,
    etiqueta,
    filtro_nombre,
    indicador_carga,
    texto_con_enlace,
    titulo_seccion,
)

logger = logging.getLogger(__name__)

RUTA = "/registro"

ALERTA_CORREO_DUPLICADO = Alerta(
    "Este correo ya está registrado",
    "Si ya tienes una cuenta, inicia sesión. Si no recuerdas tu contraseña, puedes restablecerla.",
)

# Clase representativa para construir el formulario y la pantalla de éxito, 
# además, se suscribe al ViewModel, vuelve a repintar y si hay alerta, se desplaza hasta arriba de la interfaz para visualizarse
class RegistroView:
    """Pantalla de registro de estudiantes y su confirmación."""

    def __init__(self, vm: RegistroViewModel) -> None:
        self._vm = vm

        self._banner = BannerAlerta()
        self._nombre = CampoFormulario(
            "Nombre(s)",
            on_change=vm.set_nombre,
            capitalization=ft.TextCapitalization.WORDS,
            keyboard_type=ft.KeyboardType.NAME,
            autofill=ft.AutofillHint.GIVEN_NAME,
            input_filter=filtro_nombre(),
        )
        self._apellido_paterno = CampoFormulario(
            "Apellido paterno",
            on_change=vm.set_apellido_paterno,
            capitalization=ft.TextCapitalization.WORDS,
            keyboard_type=ft.KeyboardType.NAME,
            autofill=ft.AutofillHint.FAMILY_NAME,
            input_filter=filtro_nombre(),
        )
        self._apellido_materno = CampoFormulario(
            "Apellido materno",
            on_change=vm.set_apellido_materno,
            capitalization=ft.TextCapitalization.WORDS,
            keyboard_type=ft.KeyboardType.NAME,
            input_filter=filtro_nombre(),
        )
        self._apellido_paterno.control.expand = True
        self._apellido_materno.control.expand = True

        self._opciones_transporte = {
            MedioTransporte.VEHICULO: TarjetaOpcion(
                ft.Icons.DIRECTIONS_CAR_OUTLINED,
                "Automóvil",
                lambda _: vm.set_medio_transporte(MedioTransporte.VEHICULO),
            ),
            MedioTransporte.MOTOCICLETA: TarjetaOpcion(
                ft.Icons.TWO_WHEELER,
                "Motocicleta",
                lambda _: vm.set_medio_transporte(MedioTransporte.MOTOCICLETA),
            ),
        }
        self._error_transporte = MensajeError()

        self._correo = CampoFormulario(
            "Correo institucional",
            on_change=vm.set_correo,
            icono=ft.Icons.MAIL_OUTLINE,
            ayuda="Solo se aceptan correos "
            + " o ".join(f"@{d}" for d in DOMINIOS_CORREO_PERMITIDOS),
            keyboard_type=ft.KeyboardType.EMAIL,
            autofill=ft.AutofillHint.EMAIL,
        )
        self._banner_duplicado = BannerAlerta(
            acciones=[
                ("Iniciar sesión", self._on_ir_a_login),
                ("Restablecer contraseña", self._on_ir_a_recuperar),
            ]
        )
        self._password = CampoFormulario(
            "Contraseña",
            on_change=vm.set_password,
            icono=ft.Icons.LOCK_OUTLINE,
            password=True,
            autofill=ft.AutofillHint.NEW_PASSWORD,
        )
        self._requisitos = ListaRequisitos(list(TEXTOS_REQUISITOS.values()))
        self._confirmar = CampoFormulario(
            "Confirmar contraseña",
            on_change=vm.set_confirmar_password,
            icono=ft.Icons.LOCK_OUTLINE,
            password=True,
            autofill=ft.AutofillHint.NEW_PASSWORD,
            on_submit=self._on_crear_cuenta,
        )
        self._boton = boton_principal("Crear cuenta", self._on_crear_cuenta)
        self._cargando = indicador_carga()

        self._formulario = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=20,
            controls=[
                encabezado_pagina(
                    "Crea tu cuenta",
                    "Regístrate con tus datos para consultar la disponibilidad del estacionamiento.",
                    self._on_ir_a_login,
                ),
                self._banner.control,
                titulo_seccion("Datos personales"),
                self._nombre.control,
                ft.Row(
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[self._apellido_paterno.control, self._apellido_materno.control],
                ),
                ft.Column(
                    spacing=8,
                    controls=[
                        etiqueta("Medio de transporte"),
                        ft.Row(
                            spacing=12,
                            controls=[t.control for t in self._opciones_transporte.values()],
                        ),
                        self._error_transporte.control,
                    ],
                ),
                titulo_seccion("Datos de acceso"),
                self._correo.control,
                self._banner_duplicado.control,
                self._password.control,
                self._requisitos.control,
                self._confirmar.control,
                ft.Container(height=4),
                ft.Row(controls=[self._boton]),
                texto_con_enlace("¿Ya tienes cuenta?", "Inicia sesión", self._on_ir_a_login),
                ft.Container(height=8),
            ],
        )

        self._pantalla_exito = PantallaExito(
            vm.titulo_exito, "Ir a iniciar sesión", self._on_ir_a_login
        )
        self._detalle_exito = self._pantalla_exito.detalle
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
        self._formulario.visible = not vm.registro_completado
        self._exito.visible = vm.registro_completado
        if vm.registro_completado:
            self._detalle_exito.value = vm.detalle_exito
            return

        self._banner.mostrar(vm.alerta)
        self._nombre.sincronizar(vm.nombre, vm.error("nombre"))
        self._apellido_paterno.sincronizar(vm.apellido_paterno, vm.error("apellido_paterno"))
        self._apellido_materno.sincronizar(vm.apellido_materno, vm.error("apellido_materno"))

        error_transporte = vm.error("medio_transporte")
        for medio, tarjeta in self._opciones_transporte.items():
            tarjeta.sincronizar(vm.medio_transporte == medio, error_transporte is not None)
        self._error_transporte.mostrar(error_transporte)

        self._correo.sincronizar(vm.correo, vm.error("correo"), vm.correo_duplicado)
        self._banner_duplicado.mostrar(ALERTA_CORREO_DUPLICADO if vm.correo_duplicado else None)
        self._password.sincronizar(vm.password, vm.error("password"))
        self._requisitos.sincronizar([cumplido for _, cumplido in vm.requisitos_password])
        self._confirmar.sincronizar(vm.confirmar_password, vm.error("confirmar_password"))

        self._boton.disabled = not vm.puede_enviar
        self._boton.content = self._cargando if vm.cargando else "Crear cuenta"

    # --- View -> ViewModel ---

    async def _on_crear_cuenta(self, _e: ft.Event) -> None:
        await self._vm.crear_cuenta()
        if self._vm.alerta is not None:
            # La alerta queda arriba del formulario: se lleva al usuario hasta ella.
            try:
                await self._formulario.scroll_to(offset=0, duration=300)
            except RuntimeError:
                logger.debug("Formulario sin montar; no se desplaza")

    async def _on_ir_a_login(self, _e: ft.Event) -> None:
        await self._vm.ir_a_login()

    async def _on_ir_a_recuperar(self, _e: ft.Event) -> None:
        await self._vm.ir_a_recuperar()
