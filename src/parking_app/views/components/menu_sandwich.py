"""Menú lateral (sándwich) con los datos del estudiante, perfil y cierre de sesión."""

from collections.abc import Callable
from typing import Any

import flet as ft

from parking_app.core import theme

Handler = Callable[[Any], Any]

ALTO_PREDETERMINADO = 760
# Margen para barra de estado / gestos que SafeArea descuenta en el teléfono.
MARGEN_VERTICAL = 48


def _mi_perfil() -> ft.Container:
    # "Modificación de datos de usuario" está fuera de la Fase 1: la opción se
    # muestra como en el mockup, pero deshabilitada.
    return ft.Container(
        border_radius=theme.RADIO_CAMPO,
        bgcolor=theme.SELECCION_FONDO,
        padding=ft.Padding.symmetric(vertical=12, horizontal=12),
        opacity=0.6,
        tooltip="Disponible próximamente",
        content=ft.Row(
            spacing=14,
            controls=[
                ft.Container(
                    width=38,
                    height=38,
                    border_radius=10,
                    bgcolor=theme.ICONO_VERDE_FONDO,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.PERSON_OUTLINE, color=theme.VERDE_OSCURO, size=22),
                ),
                ft.Column(
                    expand=True,
                    spacing=2,
                    controls=[
                        ft.Text("Mi perfil", size=15, weight=ft.FontWeight.W_700,
                                color=theme.TEXTO),
                        ft.Text("Disponible próximamente", size=12,
                                color=theme.TEXTO_SECUNDARIO),
                    ],
                ),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, color=theme.TEXTO_SECUNDARIO, size=20),
            ],
        ),
    )


class MenuSandwich:
    def __init__(self, on_cerrar: Handler, on_cerrar_sesion: Handler) -> None:
        self._iniciales = ft.Text(size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
        self._nombre = ft.Text(size=19, weight=ft.FontWeight.BOLD, color=theme.TEXTO)
        self._numero_control = ft.Text(size=13, color=theme.TEXTO_SECUNDARIO)
        self._correo = ft.Text(size=13, color=theme.TEXTO_SECUNDARIO)
        self._texto_salir = ft.Text(
            "Cerrar sesión", size=16, weight=ft.FontWeight.W_600, color=theme.COLOR_ERROR
        )
        self.boton_cerrar_sesion = ft.Container(
            height=52,
            border_radius=theme.RADIO_CAMPO,
            border=ft.Border.all(1.5, theme.COLOR_ERROR),
            alignment=ft.Alignment.CENTER,
            on_click=on_cerrar_sesion,
            content=ft.Row(
                tight=True,
                spacing=10,
                controls=[
                    ft.Icon(ft.Icons.LOGOUT, color=theme.COLOR_ERROR, size=20),
                    self._texto_salir,
                ],
            ),
        )
        boton_cerrar_menu = ft.Container(
            width=44,
            height=44,
            border_radius=12,
            border=ft.Border.all(1, theme.BORDE_CAMPO),
            alignment=ft.Alignment.CENTER,
            on_click=on_cerrar,
            tooltip="Cerrar menú",
            content=ft.Icon(ft.Icons.CLOSE, color=theme.TEXTO, size=22),
        )
        avatar = ft.Container(
            width=64,
            height=64,
            border_radius=32,
            bgcolor=theme.VERDE_OSCURO,
            alignment=ft.Alignment.CENTER,
            content=self._iniciales,
        )

        # El drawer acomoda su contenido en una lista con scroll: para dejar
        # "Cerrar sesión" al fondo, el contenedor toma la altura de la pantalla.
        self._contenedor = ft.Container(
            height=ALTO_PREDETERMINADO,
            padding=ft.Padding.symmetric(vertical=20, horizontal=20),
            content=ft.Column(
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.END, controls=[boton_cerrar_menu]),
                    ft.Container(height=16),
                    ft.Row(controls=[avatar]),
                    ft.Container(height=14),
                    self._nombre,
                    ft.Container(height=6),
                    self._numero_control,
                    self._correo,
                    ft.Divider(height=40, color=theme.BORDE_CAMPO),
                    _mi_perfil(),
                    ft.Container(expand=True),
                    self.boton_cerrar_sesion,
                ],
            ),
        )
        self.control = ft.NavigationDrawer(
            bgcolor=theme.MAPA_FONDO,
            width=292,
            controls=[ft.SafeArea(content=self._contenedor)],
        )

    def ajustar_altura(self, alto_pantalla: float | None) -> None:
        if alto_pantalla:
            self._contenedor.height = max(480, alto_pantalla - MARGEN_VERTICAL)

    def sincronizar(self, iniciales: str, nombre: str, numero_control: str, correo: str,
                    cerrando_sesion: bool) -> None:
        self._iniciales.value = iniciales
        self._nombre.value = nombre
        self._numero_control.value = numero_control
        self._correo.value = correo
        self._texto_salir.value = "Cerrando sesión…" if cerrando_sesion else "Cerrar sesión"
        self.boton_cerrar_sesion.disabled = cerrando_sesion
