import logging

import flet as ft

from parking_app.core import theme
from parking_app.models.usuario import MedioTransporte
from parking_app.viewmodels.perfil_viewmodel import PerfilViewModel
from parking_app.views.components.formulario import (
    BannerAlerta,
    BannerExito,
    CampoFormulario,
    MensajeError,
    TarjetaOpcion,
    actualizar,
    barra_titulo,
    boton_principal,
    etiqueta,
    filtro_nombre,
    indicador_carga,
    opcion_navegacion,
    titulo_seccion,
)

logger = logging.getLogger(__name__)

RUTA = "/perfil"


def _campo_nombre(texto: str, on_change, autofill: ft.AutofillHint | None = None) -> CampoFormulario:
    return CampoFormulario(
        texto,
        on_change=on_change,
        capitalization=ft.TextCapitalization.WORDS,
        keyboard_type=ft.KeyboardType.NAME,
        autofill=autofill,
        input_filter=filtro_nombre(),
    )


# Clase representativa de la pantalla "Mi perfil": tarjeta del estudiante, datos
# personales editables, correo de solo lectura y acceso a cambiar la contraseña.
class PerfilView:
    def __init__(self, vm: PerfilViewModel) -> None:
        self._vm = vm

        self._banner_exito = BannerExito()
        self._banner = BannerAlerta()

        self._iniciales = ft.Text(size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        self._nombre_tarjeta = ft.Text(size=18, weight=ft.FontWeight.BOLD, color=theme.TEXTO)
        self._rol = ft.Text(size=13, color=theme.TEXTO_SECUNDARIO)
        tarjeta = ft.Container(
            bgcolor=theme.SUPERFICIE_ELEVADA,
            border=ft.Border.all(1, theme.BORDE_CAMPO),
            border_radius=16,
            padding=ft.Padding.symmetric(vertical=16, horizontal=16),
            content=ft.Row(
                spacing=16,
                controls=[
                    ft.Container(
                        width=60,
                        height=60,
                        border_radius=30,
                        bgcolor=theme.VERDE_OSCURO,
                        alignment=ft.Alignment.CENTER,
                        content=self._iniciales,
                    ),
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[self._nombre_tarjeta, self._rol],
                    ),
                ],
            ),
        )

        self._nombre = _campo_nombre("Nombre(s)", vm.set_nombre, ft.AutofillHint.GIVEN_NAME)
        self._apellido_paterno = _campo_nombre(
            "Apellido paterno", vm.set_apellido_paterno, ft.AutofillHint.FAMILY_NAME
        )
        self._apellido_materno = _campo_nombre("Apellido materno", vm.set_apellido_materno)
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
        self._banner_reserva = BannerAlerta()

        # RF-02: el correo se muestra, pero no se edita.
        self._correo = CampoFormulario(
            "Correo institucional",
            on_change=lambda _: None,
            icono=ft.Icons.LOCK_OUTLINE,
            ayuda="El correo institucional no se puede modificar.",
        )
        self._correo.campo.read_only = True
        self._correo.campo.color = theme.TEXTO_SECUNDARIO
        self._correo.campo.focused_border_color = theme.BORDE_CAMPO

        self._boton = boton_principal("Guardar cambios", self._on_guardar)
        self._cargando = indicador_carga()

        self._contenido = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            spacing=20,
            controls=[
                barra_titulo("Mi perfil", self._on_regresar),
                self._banner_exito.control,
                self._banner.control,
                tarjeta,
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
                        self._banner_reserva.control,
                    ],
                ),
                titulo_seccion("Cuenta"),
                self._correo.control,
                titulo_seccion("Seguridad"),
                opcion_navegacion(
                    ft.Icons.LOCK_OUTLINE,
                    "Cambiar contraseña",
                    "Se pedirá tu contraseña actual",
                    self._on_cambiar_password,
                ),
                ft.Container(height=4),
                ft.Row(controls=[self._boton]),
                ft.Container(height=8),
            ],
        )

        self.view = ft.View(
            route=RUTA,
            bgcolor=theme.FONDO,
            padding=ft.Padding.symmetric(horizontal=24, vertical=16),
            controls=[ft.SafeArea(expand=True, content=self._contenido)],
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
        self._banner_exito.mostrar(vm.mensaje_exito)
        self._banner.mostrar(vm.alerta)

        self._iniciales.value = vm.iniciales
        self._nombre_tarjeta.value = vm.nombre_completo
        self._rol.value = vm.texto_rol

        self._nombre.sincronizar(vm.nombre, vm.error("nombre"))
        self._apellido_paterno.sincronizar(vm.apellido_paterno, vm.error("apellido_paterno"))
        self._apellido_materno.sincronizar(vm.apellido_materno, vm.error("apellido_materno"))

        error_transporte = vm.error("medio_transporte")
        bloqueado = vm.alerta_reserva is not None
        for medio, tarjeta in self._opciones_transporte.items():
            seleccionada = vm.medio_transporte == medio
            tarjeta.sincronizar(
                seleccionada,
                error_transporte is not None or (bloqueado and seleccionada),
            )
        self._error_transporte.mostrar(error_transporte)
        self._banner_reserva.mostrar(vm.alerta_reserva)

        self._correo.sincronizar(vm.correo)

        self._boton.disabled = not vm.puede_guardar
        self._boton.content = self._cargando if vm.cargando else "Guardar cambios"

    # --- View -> ViewModel ---

    async def _on_guardar(self, _e: ft.Event) -> None:
        await self._vm.guardar()
        if self._vm.alerta is not None or self._vm.guardado:
            # Los avisos van arriba del formulario: se lleva al usuario hasta ellos.
            try:
                await self._contenido.scroll_to(offset=0, duration=300)
            except RuntimeError:
                logger.debug("Perfil sin montar; no se desplaza")

    async def _on_regresar(self, _e: ft.Event) -> None:
        await self._vm.regresar()

    async def _on_cambiar_password(self, _e: ft.Event) -> None:
        await self._vm.ir_a_cambiar_password()
