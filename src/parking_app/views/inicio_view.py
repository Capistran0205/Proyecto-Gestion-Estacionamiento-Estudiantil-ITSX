import flet as ft

from parking_app.core import theme
from parking_app.viewmodels.inicio_viewmodel import InicioViewModel
from parking_app.viewmodels.ocupacion_viewmodel import NivelDisponibilidad
from parking_app.views.components.barra_navegacion import Seccion, barra_navegacion
from parking_app.views.components.formulario import actualizar, icono_destacado
from parking_app.views.components.menu_sandwich import MenuSandwich
from parking_app.views.components.pildora_conexion import PildoraConexion

RUTA = "/inicio"

_COLOR_NIVEL = {
    NivelDisponibilidad.ALTA: theme.colores_estado("libre").acento,
    NivelDisponibilidad.MEDIA: theme.NARANJA,
    NivelDisponibilidad.LLENO: theme.COLOR_ERROR,
    NivelDisponibilidad.SIN_DATOS: theme.TEXTO_TENUE,
}


class _Contador:
    """Recuadro "[N] Libres/Ocupados/Reservados" con los colores del estado."""

    def __init__(self, estado: str, etiqueta: str) -> None:
        colores = theme.colores_estado(estado)
        self.numero = ft.Text(size=26, weight=ft.FontWeight.BOLD, color=colores.acento)
        self.control = ft.Container(
            expand=True,
            height=72,
            border_radius=12,
            bgcolor=colores.fondo,
            border=ft.Border.all(1, colores.acento),
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                tight=True,
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    self.numero,
                    ft.Text(etiqueta, size=12, weight=ft.FontWeight.W_600, color=colores.acento),
                ],
            ),
        )


def _tarjeta_modulo(icono, fondo_icono, color_icono, titulo, subtitulo, on_click,
                    habilitado=True) -> ft.Container:
    return ft.Container(
        expand=True,
        height=150,
        border_radius=18,
        bgcolor=theme.MAPA_FONDO,
        border=ft.Border.all(1, theme.BORDE_CAMPO),
        padding=ft.Padding.symmetric(vertical=16, horizontal=8),
        on_click=on_click if habilitado else None,
        opacity=1.0 if habilitado else 0.6,
        tooltip=None if habilitado else "Disponible próximamente",
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            tight=True,
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                icono_destacado(icono, fondo_icono, color_icono),
                ft.Container(height=4),
                ft.Text(titulo, size=16, weight=ft.FontWeight.W_700, color=theme.TEXTO),
                ft.Text(subtitulo, size=13, color=theme.TEXTO_SECUNDARIO,
                        text_align=ft.TextAlign.CENTER),
            ],
        ),
    )


class InicioView:
    """Menú principal con resumen en vivo y menú sándwich (perfil / cerrar sesión)."""

    def __init__(self, vm: InicioViewModel) -> None:
        self._vm = vm
        self._menu = MenuSandwich(self._on_cerrar_menu, self._on_cerrar_sesion)

        self._saludo = ft.Text(size=14, color=theme.TEXTO_SECUNDARIO)
        self._nombre = ft.Text(size=22, weight=ft.FontWeight.BOLD, color=theme.TEXTO)
        boton_menu = ft.Container(
            width=48,
            height=48,
            border_radius=24,
            bgcolor=theme.VERDE_OSCURO,
            alignment=ft.Alignment.CENTER,
            on_click=self._on_abrir_menu,
            tooltip="Menú",
            content=ft.Icon(ft.Icons.MENU, color=ft.Colors.WHITE, size=24),
        )

        self._pildora = PildoraConexion()
        self._libres = ft.Text(size=48, weight=ft.FontWeight.BOLD, color=theme.TEXTO)
        self._total = ft.Text(size=17, color=theme.TEXTO_SECUNDARIO)
        self._barra = ft.ProgressBar(
            value=0, bar_height=8, border_radius=4, bgcolor=theme.BORDE_CAMPO
        )
        self._punto_nivel = ft.Container(width=8, height=8, border_radius=4)
        self._texto_nivel = ft.Text(size=13, color=theme.TEXTO_SECUNDARIO)
        self._contadores = {
            "libres": _Contador("libre", "Libres"),
            "ocupados": _Contador("ocupado", "Ocupados"),
            "reservados": _Contador("reservado", "Reservados"),
        }

        tarjeta_estado = ft.Container(
            bgcolor=theme.MAPA_FONDO,
            border=ft.Border.all(1, theme.BORDE_CAMPO),
            border_radius=20,
            padding=20,
            content=ft.Column(
                spacing=14,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text("Estado del estacionamiento", size=14,
                                    weight=ft.FontWeight.W_600, color=theme.TEXTO,
                                    expand=True),
                            self._pildora.control,
                        ]
                    ),
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                        controls=[
                            self._libres,
                            ft.Container(padding=ft.Padding.only(bottom=10),
                                         content=self._total),
                        ],
                    ),
                    self._barra,
                    ft.Row(spacing=8, controls=[self._punto_nivel, self._texto_nivel]),
                    ft.Row(spacing=10, controls=[c.control for c in self._contadores.values()]),
                ],
            ),
        )
        modulos = ft.Row(
            spacing=12,
            controls=[
                _tarjeta_modulo(ft.Icons.GRID_VIEW, theme.ICONO_VERDE_FONDO, theme.VERDE_OSCURO,
                                "Ver Mapa", "Ocupación de Cajones", self._on_ocupacion),
                # Historial queda fuera del alcance de la Fase 1.
                _tarjeta_modulo(ft.Icons.BAR_CHART, theme.ICONO_AZUL_FONDO, theme.AZUL,
                                "Historial", "Horas promedio", None, habilitado=False),
            ],
        )
        contenido = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Container(
                    padding=ft.Padding.only(left=20, right=20, top=16, bottom=16),
                    content=ft.Row(
                        controls=[
                            ft.Column(expand=True, spacing=2,
                                      controls=[self._saludo, self._nombre]),
                            boton_menu,
                        ]
                    ),
                ),
                ft.Divider(height=1, color=theme.BORDE_CAMPO),
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=20, vertical=20),
                    content=ft.Column(
                        spacing=16,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                        controls=[
                            tarjeta_estado,
                            ft.Container(height=4),
                            ft.Text("Módulos", size=16, weight=ft.FontWeight.W_600,
                                    color=theme.TEXTO),
                            modulos,
                        ],
                    ),
                ),
            ],
        )

        self.view = ft.View(
            route=RUTA,
            bgcolor=theme.FONDO,
            padding=0,
            spacing=0,
            end_drawer=self._menu.control,
            controls=[
                ft.SafeArea(
                    expand=True,
                    content=ft.Column(
                        expand=True,
                        spacing=0,
                        controls=[
                            contenido,
                            barra_navegacion(Seccion.INICIO, None, self._on_ocupacion),
                        ],
                    ),
                )
            ],
        )
        self._render()

    # --- Ciclo de vida (lo invoca el router) ---

    def montar(self) -> None:
        self._vm.add_listener(self._on_cambio)
        self._vm.ocupacion.add_listener(self._on_cambio)

    def desmontar(self) -> None:
        self._vm.remove_listener(self._on_cambio)
        self._vm.ocupacion.remove_listener(self._on_cambio)

    # --- ViewModel -> View ---

    def _on_cambio(self) -> None:
        self._render()
        actualizar(self.view)

    def _render(self) -> None:
        vm, ocupacion = self._vm, self._vm.ocupacion
        self._saludo.value = vm.saludo
        self._nombre.value = vm.nombre_corto
        self._menu.sincronizar(vm.iniciales, vm.nombre_completo, vm.numero_control, vm.correo,
                               vm.cerrando_sesion)

        self._pildora.sincronizar(ocupacion.estado_conexion, ocupacion.texto_conexion)
        self._libres.value = str(ocupacion.libres)
        self._total.value = f"/ {ocupacion.total} cajones libres"
        color_nivel = _COLOR_NIVEL[ocupacion.nivel_disponibilidad]
        self._barra.value = ocupacion.porcentaje_ocupado / 100
        self._barra.color = color_nivel
        self._punto_nivel.bgcolor = color_nivel
        self._texto_nivel.value = ocupacion.texto_disponibilidad
        self._contadores["libres"].numero.value = str(ocupacion.libres)
        self._contadores["ocupados"].numero.value = str(ocupacion.ocupados)
        self._contadores["reservados"].numero.value = str(ocupacion.reservados)

    # --- View -> ViewModel ---

    async def _on_abrir_menu(self, _e: ft.Event) -> None:
        try:
            self._menu.ajustar_altura(self.view.page.height)
        except (RuntimeError, AttributeError):
            pass
        self._render()
        await self.view.show_end_drawer()

    async def _on_cerrar_menu(self, _e: ft.Event) -> None:
        await self.view.close_end_drawer()

    async def _on_cerrar_sesion(self, _e: ft.Event) -> None:
        await self._vm.cerrar_sesion()

    async def _on_ocupacion(self, _e: ft.Event) -> None:
        await self._vm.ir_a_ocupacion()
