import flet as ft

from parking_app.core import theme

# Clase para construir la tarjeta visual de cada cajón de estacionamiento del C1 hasta el C4
# dicha etiqueta, contiene un indicador circular y texto del estado, con un fondo y color de texto visuales y representativos 
class TarjetaCajon:
    """Cajón del mapa: etiqueta, indicador circular y estado con el color del estado."""

    def __init__(self, etiqueta: str) -> None:
        self._indicador = ft.Container(width=42, height=42, border_radius=21)
        self._texto = ft.Text(
            size=12,
            weight=ft.FontWeight.W_600,
            text_align=ft.TextAlign.CENTER,
            max_lines=2,
        )
        self.control = ft.Container(
            expand=True,
            height=170,
            border_radius=14,
            padding=ft.Padding.symmetric(vertical=14, horizontal=4),
            content=ft.Column(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(etiqueta, size=20, weight=ft.FontWeight.BOLD, color=theme.TEXTO),
                    self._indicador,
                    ft.Container(
                        height=32,
                        alignment=ft.Alignment.CENTER,
                        content=self._texto,
                    ),
                ],
            ),
        )

    @property
    def color_acento(self) -> str:
        return self._indicador.bgcolor

    def sincronizar(self, estado: str, texto_estado: str) -> None:
        colores = theme.colores_estado(estado)
        self.control.bgcolor = colores.fondo
        self.control.border = ft.Border.all(2, colores.acento)
        self._indicador.bgcolor = colores.acento
        self._texto.value = texto_estado
        self._texto.color = colores.acento
