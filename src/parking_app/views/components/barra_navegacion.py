from collections.abc import Callable
from enum import StrEnum
from typing import Any

import flet as ft

from parking_app.core import theme

Handler = Callable[[Any], Any]

# Clase para representar las secciones con las que cuenta el sistema
class Seccion(StrEnum):
    INICIO = "inicio"
    OCUPACION = "ocupacion"
    HISTORIAL = "historial"


def _boton(icono: ft.IconData, texto: str, on_click: Handler | None, activo: bool,
           habilitado: bool) -> ft.Container:
    if activo:
        color = theme.VERDE_AZULADO
    elif habilitado:
        color = theme.TEXTO_SECUNDARIO
    else:
        color = theme.TEXTO_TENUE
    return ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(vertical=6),
        on_click=on_click if habilitado and not activo else None,
        tooltip=None if habilitado else "Disponible próximamente",
        opacity=1.0 if habilitado else 0.6,
        content=ft.Column(
            tight=True,
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(icono, color=color, size=24),
                ft.Text(
                    texto, size=12, color=color, weight=ft.FontWeight.W_600 if activo else None
                ),
            ],
        ),
    )


def barra_navegacion(activa: Seccion, on_inicio: Handler, on_ocupacion: Handler) -> ft.Container:
    """Barra inferior Inicio / Ocupación / Historial (Historial: fuera de la Fase 1)."""
    return ft.Container(
        bgcolor=theme.BARRA_INFERIOR,
        border=ft.Border.only(top=ft.BorderSide(1, theme.BORDE_CAMPO)),
        padding=ft.Padding.symmetric(vertical=10),
        content=ft.Row(
            controls=[
                _boton(ft.Icons.HOME_OUTLINED, "Inicio", on_inicio,
                       activa == Seccion.INICIO, True),
                _boton(ft.Icons.GRID_VIEW, "Ocupación", on_ocupacion,
                       activa == Seccion.OCUPACION, True),
                _boton(ft.Icons.BAR_CHART, "Historial", None,
                       activa == Seccion.HISTORIAL, False),
            ]
        ),
    )
