import flet as ft

from parking_app.core import theme
from parking_app.services.mqtt_service import EstadoConexion

# (fondo, punto, texto) por estado; el resto usa los colores de "sin conexión".
_COLORES = {
    EstadoConexion.CONECTADO: (theme.ALERTA_FONDO, theme.NARANJA, theme.ALERTA_TEXTO),
    EstadoConexion.CONECTANDO: (theme.SUPERFICIE_ELEVADA, theme.TEXTO_TENUE, theme.TEXTO_SECUNDARIO),
    EstadoConexion.RECONECTANDO: (theme.SUPERFICIE_ELEVADA, theme.TEXTO_TENUE, theme.TEXTO_SECUNDARIO),
}
_SIN_CONEXION = ("#2E1A1A", theme.COLOR_ERROR, "#F4B4B4")

# Clase para construir y mostrar el estado actual de la conexión del usuarios con el servidor MQTT en formato de un pequeña pildora color naranja
class PildoraConexion:
    """Indicador "En vivo" / "Reconectando…" / "Sin conexión"."""

    def __init__(self) -> None:
        self._punto = ft.Container(width=8, height=8, border_radius=4)
        self._texto = ft.Text(size=13, weight=ft.FontWeight.W_600)
        self.control = ft.Container(
            padding=ft.Padding.symmetric(vertical=6, horizontal=12),
            border_radius=20,
            content=ft.Row(tight=True, spacing=6, controls=[self._punto, self._texto]),
        )

    @property
    def texto(self) -> str:
        return self._texto.value

    def sincronizar(self, estado: EstadoConexion, texto: str) -> None:
        fondo, punto, color_texto = _COLORES.get(estado, _SIN_CONEXION)
        self.control.bgcolor = fondo
        self._punto.bgcolor = punto
        self._texto.value = texto
        self._texto.color = color_texto
