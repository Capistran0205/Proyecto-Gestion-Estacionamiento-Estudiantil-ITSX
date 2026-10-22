from collections.abc import Callable, Iterable
from typing import Any

import flet as ft

from parking_app.core import theme

ALTO = 170
OPACIDAD_ATENUADA = 0.45


# Clase para construir la tarjeta visual de cada cajón de estacionamiento del C1 hasta el C4
# dicha etiqueta, contiene un indicador circular y texto del estado, con un fondo y color de texto visuales y representativos
class TarjetaCajon:
    """Cajón del mapa: etiqueta, indicador circular y estado con el color del estado.

    Con `on_click`, la tarjeta se puede tocar (solo responde si está marcada como
    tocable). La seleccionada lleva una palomita en la esquina.
    """

    def __init__(self, etiqueta: str, on_click: Callable[[Any], Any] | None = None) -> None:
        self._on_click = on_click
        self._indicador = ft.Container(width=42, height=42, border_radius=21)
        # 11 px: "Bloqueado" cabe en una línea en la tarjeta más angosta (4 por fila).
        self._texto = ft.Text(
            size=11,
            weight=ft.FontWeight.W_600,
            text_align=ft.TextAlign.CENTER,
            max_lines=2,
        )
        self._etiqueta = ft.Text(etiqueta, size=20, weight=ft.FontWeight.BOLD, color=theme.TEXTO)
        self._tarjeta = ft.Container(
            border_radius=14,
            padding=ft.Padding.symmetric(vertical=14, horizontal=2),
            content=ft.Column(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    self._etiqueta,
                    self._indicador,
                    ft.Container(
                        height=32,
                        alignment=ft.Alignment.CENTER,
                        content=self._texto,
                    ),
                ],
            ),
        )
        self._palomita = ft.Container(
            visible=False,
            width=26,
            height=26,
            border_radius=13,
            bgcolor=theme.colores_estado("libre").acento,
            border=ft.Border.all(2, theme.MAPA_FONDO),
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ft.Icons.CHECK, size=16, color=theme.FONDO),
        )
        self.control = ft.Container(
            expand=True,
            height=ALTO,
            content=ft.Stack(
                clip_behavior=ft.ClipBehavior.NONE,
                controls=[
                    ft.Container(left=0, right=0, top=0, bottom=0, content=self._tarjeta),
                    ft.Container(right=-8, top=-8, content=self._palomita),
                ],
            ),
        )

    @property
    def color_acento(self) -> str:
        return self._indicador.bgcolor

    @property
    def seleccionada(self) -> bool:
        return self._palomita.visible

    def sincronizar(
        self,
        estado: str,
        texto_estado: str,
        tocable: bool = False,
        seleccionada: bool = False,
        atenuada: bool = False,
    ) -> None:
        colores = theme.colores_estado(estado)
        self._tarjeta.bgcolor = colores.fondo
        self._tarjeta.border = ft.Border.all(2, colores.acento)
        self._tarjeta.opacity = OPACIDAD_ATENUADA if atenuada else 1.0
        self._indicador.bgcolor = colores.acento
        self._texto.value = texto_estado
        self._texto.color = colores.acento
        self._palomita.visible = seleccionada
        self._tarjeta.on_click = self._on_click if tocable else None


def leyenda_estados(estados: Iterable[str], textos: dict[str, str]) -> ft.Row:
    """Puntos de color con el nombre de cada estado."""
    return ft.Row(
        wrap=True,
        spacing=16,
        run_spacing=8,
        controls=[
            ft.Row(
                tight=True,
                spacing=6,
                controls=[
                    ft.Container(
                        width=12,
                        height=12,
                        border_radius=6,
                        bgcolor=theme.colores_estado(estado).acento,
                    ),
                    ft.Text(textos[estado], size=13, color=theme.TEXTO_SECUNDARIO),
                ],
            )
            for estado in estados
        ],
    )
