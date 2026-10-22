import flet as ft

from parking_app.core import theme
from parking_app.models.cajon_estacionamiento import EstadoCajon
from parking_app.viewmodels.ocupacion_viewmodel import TEXTOS_ESTADO, OcupacionViewModel
from parking_app.views.components.barra_navegacion import Seccion, barra_navegacion
from parking_app.views.components.formulario import actualizar, boton_regresar
from parking_app.views.components.pildora_conexion import PildoraConexion
from parking_app.views.components.tarjeta_cajon import TarjetaCajon, leyenda_estados

RUTA = "/ocupacion"


def _leyenda() -> ft.Row:
    return leyenda_estados(EstadoCajon, TEXTOS_ESTADO)


def _zona_inferior() -> ft.Row:
    caseta = ft.Container(
        height=110,
        border_radius=14,
        bgcolor=theme.CASETA_FONDO,
        border=ft.Border.all(1.5, theme.AZUL),
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            tight=True,
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.HOME_OUTLINED, color=theme.AZUL_CLARO, size=24),
                ft.Text("Caseta", size=15, weight=ft.FontWeight.W_700, color=theme.TEXTO),
            ],
        ),
    )
    entrada = ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            tight=True,
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.SWAP_VERT, color=theme.VERDE_AZULADO, size=28),
                ft.Text(
                    "ENTRADA /\nSALIDA",
                    size=12,
                    weight=ft.FontWeight.W_700,
                    color=theme.VERDE_AZULADO,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        ),
    )
    zona = ft.Container(
        expand=2,
        border_radius=14,
        bgcolor=theme.ZONA_FONDO,
        border=ft.Border.all(1, theme.ZONA_BORDE),
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            tight=True,
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(ft.Icons.DIRECTIONS_CAR_OUTLINED, color=theme.ZONA_TEXTO, size=30),
                ft.Text(
                    "Zona de\ncirculación",
                    size=15,
                    weight=ft.FontWeight.W_600,
                    color=theme.ZONA_TEXTO,
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
        ),
    )
    return ft.Row(
        height=230,
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        controls=[
            ft.Column(
                expand=1,
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[caseta, entrada],
            ),
            zona,
        ],
    )


def _indicacion_reservar() -> ft.Container:
    """"Toca un cajón libre para reservarlo" (con "libre" en el color del estado)."""
    return ft.Container(
        bgcolor=theme.MAPA_FONDO,
        border=ft.Border.all(1, theme.BORDE_CAMPO),
        border_radius=theme.RADIO_CAMPO,
        padding=ft.Padding.symmetric(vertical=12, horizontal=16),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
            controls=[
                ft.Icon(ft.Icons.TOUCH_APP_OUTLINED, size=18, color=theme.VERDE_AZULADO),
                ft.Text(
                    spans=[
                        ft.TextSpan("Toca un cajón "),
                        ft.TextSpan("libre", style=ft.TextStyle(
                            weight=ft.FontWeight.BOLD,
                            color=theme.colores_estado("libre").acento)),
                        ft.TextSpan(" para reservarlo"),
                    ],
                    size=14,
                    color=theme.TEXTO,
                ),
            ],
        ),
    )

# Clase representativa para construir la interfaz para visualizar la ocupación en tiempo real de los cajones de estacionamiento
# consiste en obtener el encabezado enviado por el ESP32, el cual Muestra el encabezado ("Ocupación de cajones" y cuántos cajones están libres), 
# la píldora de conexión, la leyenda de colores, el mapa con los 4 cajones
class OcupacionView:
    """Mapa de los 4 cajones con estado en vivo por MQTT.

    La conexión la inicia y detiene el router (el ViewModel dura toda la sesión
    y lo comparte la pantalla de Inicio); esta vista solo lo observa.
    """

    def __init__(self, vm: OcupacionViewModel) -> None:
        self._vm = vm

        self._subtitulo = ft.Text(size=13, color=theme.TEXTO_SECUNDARIO)
        self._pildora = PildoraConexion()
        # Tocar un cajón libre abre la reserva (botón invisible sobre la tarjeta).
        self._tarjetas = [
            TarjetaCajon(c.etiqueta, on_click=self._al_tocar(c.etiqueta)) for c in vm.cajones
        ]
        self._actualizado = ft.Text(size=13, color=theme.TEXTO_SECUNDARIO)

        encabezado = ft.Row(
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                boton_regresar(self._on_inicio),
                ft.Column(
                    expand=True,
                    spacing=2,
                    controls=[
                        ft.Text(
                            "Ocupación de cajones",
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color=theme.TEXTO,
                        ),
                        self._subtitulo,
                    ],
                ),
                ft.Container(padding=ft.Padding.only(top=8), content=self._pildora.control),
            ],
        )
        mapa = ft.Container(
            bgcolor=theme.MAPA_FONDO,
            border=ft.Border.all(1, theme.BORDE_CAMPO),
            border_radius=20,
            padding=14,
            content=ft.Column(
                spacing=0,
                controls=[
                    ft.Row(spacing=8, controls=[t.control for t in self._tarjetas]),
                    ft.Divider(height=28, color=theme.BORDE_CAMPO),
                    _zona_inferior(),
                ],
            ),
        )
        contenido = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=20,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=20),
                    content=ft.Column(
                        spacing=20,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                        controls=[
                            ft.Container(height=4),
                            encabezado,
                            ft.Divider(height=1, color=theme.BORDE_CAMPO),
                            _leyenda(),
                            mapa,
                            ft.Row(
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=6,
                                controls=[
                                    ft.Icon(
                                        ft.Icons.SCHEDULE, size=16, color=theme.TEXTO_SECUNDARIO
                                    ),
                                    self._actualizado,
                                ],
                            ),
                            _indicacion_reservar(),
                            ft.Container(height=4),
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
            controls=[
                ft.SafeArea(
                    expand=True,
                    content=ft.Column(
                        expand=True,
                        spacing=0,
                        controls=[
                            contenido,
                            barra_navegacion(Seccion.OCUPACION, self._on_inicio, None),
                        ],
                    ),
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
        self._subtitulo.value = vm.texto_libres
        self._pildora.sincronizar(vm.estado_conexion, vm.texto_conexion)
        for tarjeta, cajon in zip(self._tarjetas, vm.cajones, strict=True):
            tarjeta.sincronizar(cajon.estado, cajon.texto_estado, tocable=cajon.seleccionable)
        self._actualizado.value = vm.texto_actualizado

    # --- View -> ViewModel ---

    def _al_tocar(self, etiqueta: str):
        async def manejar(_e: ft.Event) -> None:
            await self._vm.reservar(etiqueta)

        return manejar

    async def _on_inicio(self, _e: ft.Event) -> None:
        await self._vm.ir_a_inicio()
