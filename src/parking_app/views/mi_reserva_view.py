import logging

import flet as ft

from parking_app.core import theme
from parking_app.viewmodels.mi_reserva_viewmodel import (
    Confirmacion,
    MiReservaViewModel,
    PantallaReserva,
)
from parking_app.views.components.codigo_qr import qr_png
from parking_app.views.components.formulario import (
    BannerAlerta,
    BannerEstado,
    PantallaResultado,
    RecuadroCajon,
    actualizar,
    barra_titulo,
    boton_contorno,
    boton_peligro,
    boton_peligro_relleno,
    boton_principal,
    nota_informativa,
    tabla_detalle,
)

logger = logging.getLogger(__name__)

RUTA = "/mi-reserva"

LADO_QR = 228

# Ícono y colores (acento, fondo del círculo) de cada pantalla de resultado.
ESTILO_RESULTADO: dict[PantallaReserva, tuple[ft.IconData, str, str]] = {
    PantallaReserva.CANCELADA: (ft.Icons.CLOSE_ROUNDED, theme.TEXTO_SECUNDARIO, "#2a2a2a"),
    PantallaReserva.EXPIRADA: (ft.Icons.ACCESS_TIME_ROUNDED, theme.NARANJA, theme.ALERTA_FONDO),
    PantallaReserva.FINALIZADA: (ft.Icons.CHECK_ROUNDED, theme.VERDE_AZULADO, theme.SELECCION_FONDO),
    PantallaReserva.SIN_RESERVA: (ft.Icons.EVENT_BUSY, theme.AZUL_CLARO, theme.CASETA_FONDO),
    PantallaReserva.ERROR: (ft.Icons.CLOUD_OFF, theme.NARANJA, theme.ALERTA_FONDO),
}


def _tarjeta(contenido: ft.Control, padding: ft.Padding, radio: int = 16) -> ft.Container:
    return ft.Container(
        bgcolor=theme.SUPERFICIE_ELEVADA,
        border=ft.Border.all(1, theme.BORDE_CAMPO),
        border_radius=radio,
        padding=padding,
        content=contenido,
    )


# Clase representativa de "Mi reserva": QR, cuenta regresiva y acciones de la
# reserva, más las pantallas de resultado (cancelada, expirada, salida confirmada).
class MiReservaView:
    def __init__(self, vm: MiReservaViewModel) -> None:
        self._vm = vm
        self._codigo_mostrado: str | None = None
        self._hoja_abierta = False

        # --- Reserva activa ---
        self._banner = BannerEstado()
        self._alerta = BannerAlerta()
        self._recuadro = RecuadroCajon("reservado")

        self._qr = ft.Container(
            width=LADO_QR,
            height=LADO_QR,
            bgcolor=ft.Colors.WHITE,
            border_radius=16,
            padding=10,
            alignment=ft.Alignment.CENTER,
        )
        self._icono_conexion = ft.Icon(ft.Icons.WIFI, size=14)
        self._texto_conexion = ft.Text(size=12, weight=ft.FontWeight.W_700)
        self._chip_conexion = ft.Container(
            border_radius=12,
            padding=ft.Padding.symmetric(vertical=4, horizontal=10),
            content=ft.Row(tight=True, spacing=6,
                           controls=[self._icono_conexion, self._texto_conexion]),
        )
        self._tarjeta_qr = _tarjeta(
            ft.Column(
                spacing=14,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    self._qr,
                    ft.Text("Muestra este código en la caseta al llegar", size=13,
                            color=theme.TEXTO_SECUNDARIO, text_align=ft.TextAlign.CENTER),
                    self._chip_conexion,
                ],
            ),
            ft.Padding.symmetric(vertical=16, horizontal=16),
        )

        self._titulo_tiempo = ft.Text(size=13, color=theme.TEXTO_SECUNDARIO)
        self._detalle_tiempo = ft.Text(size=12, color=theme.TEXTO_TENUE)
        self._tiempo = ft.Text(size=26, weight=ft.FontWeight.BOLD)
        self._tarjeta_tiempo = _tarjeta(
            ft.Row(
                spacing=12,
                controls=[
                    ft.Column(expand=True, spacing=2,
                              controls=[self._titulo_tiempo, self._detalle_tiempo]),
                    self._tiempo,
                ],
            ),
            ft.Padding.symmetric(vertical=14, horizontal=16),
            radio=theme.RADIO_CAMPO,
        )

        # En uso (mockups): nota, tabla de la reserva y "Confirmar salida". Cerca del fin
        # (RF-12) aparece el recuadro naranja con "Confirmar salida" y "Extender 1 hora".
        self._nota_uso = nota_informativa(ft.Icons.INFO_OUTLINE, "")
        self._titulo_aviso = ft.Text(size=15, weight=ft.FontWeight.W_700, color=theme.TEXTO)
        self._detalle_aviso = ft.Text(size=13, color=theme.ALERTA_TEXTO)
        self._extender = ft.OutlinedButton(
            content="Extender 1 hora",
            height=54,
            expand=True,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=theme.RADIO_CAMPO),
                side=ft.BorderSide(1.5, theme.NARANJA),
                color=theme.NARANJA,
                text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_700),
            ),
            on_click=self._on_extender,
        )
        self._salida_aviso = boton_principal("Confirmar salida", self._on_salida)
        self._aviso_fin = ft.Container(
            visible=False,
            bgcolor=theme.ALERTA_FONDO,
            border=ft.Border.all(1, theme.NARANJA),
            border_radius=16,
            padding=16,
            content=ft.Column(
                spacing=16,
                controls=[
                    ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Icon(ft.Icons.SCHEDULE, size=22, color=theme.NARANJA),
                            ft.Column(expand=True, spacing=4,
                                      controls=[self._titulo_aviso, self._detalle_aviso]),
                        ],
                    ),
                    ft.Row(spacing=12, controls=[self._salida_aviso, self._extender]),
                ],
            ),
        )
        self._tabla_uso = ft.Container()
        self._filas_mostradas: list[tuple[str, str]] = []

        self._cancelar = boton_peligro("Cancelar reserva", ft.Icons.CLOSE, self._on_cancelar)
        self._salida = boton_principal("Confirmar salida", self._on_salida)
        self._activa = ft.Column(
            expand=True,
            spacing=16,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=14,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    controls=[
                        self._banner.control,
                        self._alerta.control,
                        self._recuadro.control,
                        self._tarjeta_qr,
                        self._tarjeta_tiempo,
                        self._aviso_fin,
                        self._nota_uso,
                        self._tabla_uso,
                    ],
                ),
                ft.Column(
                    spacing=12,
                    controls=[ft.Row(controls=[self._salida]),
                              ft.Row(controls=[self._cancelar])],
                ),
                ft.Container(height=8),
            ],
        )

        self._cargando = ft.Container(
            expand=True,
            alignment=ft.Alignment.CENTER,
            content=ft.ProgressRing(width=36, height=36, color=theme.VERDE_AZULADO),
        )
        self._resultado = PantallaResultado(self._on_resultado)
        self._barra = barra_titulo("Mi reserva", self._on_regresar)

        # --- Hoja de confirmación (cancelar / confirmar salida) ---
        self._titulo_hoja = ft.Text(size=20, weight=ft.FontWeight.BOLD, color=theme.TEXTO)
        self._detalle_hoja = ft.Text(size=14, color=theme.TEXTO_SECUNDARIO)
        self._confirmar_peligro = boton_peligro_relleno("", self._on_confirmar)
        self._confirmar_normal = boton_principal("", self._on_confirmar)
        self._hoja = ft.BottomSheet(
            bgcolor=theme.SUPERFICIE_ELEVADA,
            show_drag_handle=True,
            on_dismiss=self._on_hoja_cerrada,
            content=ft.Container(
                padding=ft.Padding.only(left=24, right=24, bottom=24),
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    controls=[
                        self._titulo_hoja,
                        self._detalle_hoja,
                        ft.Container(height=8),
                        ft.Row(controls=[self._confirmar_peligro]),
                        ft.Row(controls=[self._confirmar_normal]),
                        ft.Row(controls=[boton_contorno("Mantener reserva", self._on_mantener)]),
                    ],
                ),
            ),
        )

        self.view = ft.View(
            route=RUTA,
            bgcolor=theme.FONDO,
            padding=ft.Padding.symmetric(horizontal=24, vertical=16),
            controls=[
                ft.SafeArea(
                    expand=True,
                    content=ft.Column(
                        expand=True,
                        spacing=20,
                        controls=[
                            self._barra,
                            ft.Stack(expand=True, controls=[
                                self._cargando, self._activa, self._resultado.control,
                            ]),
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
        self._vm.liberar()
        if self._hoja_abierta:
            self._cerrar_hoja()

    # --- ViewModel -> View ---

    def _on_cambio(self) -> None:
        self._render()
        actualizar(self.view)

    def _render(self) -> None:
        vm = self._vm
        pantalla = vm.pantalla
        resultado = vm.resultado
        self._cargando.visible = pantalla == PantallaReserva.CARGANDO
        self._activa.visible = vm.activa
        # Las pantallas de resultado del mockup no llevan la barra de título.
        self._barra.visible = pantalla not in ESTILO_RESULTADO or pantalla in (
            PantallaReserva.SIN_RESERVA, PantallaReserva.ERROR)
        if resultado is not None and pantalla in ESTILO_RESULTADO:
            icono, color, fondo = ESTILO_RESULTADO[pantalla]
            self._resultado.mostrar(resultado.titulo, resultado.detalle, resultado.boton,
                                    icono, color, fondo)
        else:
            self._resultado.ocultar()
        self._sincronizar_hoja()
        if not vm.activa:
            return

        self._banner.mostrar(vm.banner, advertencia=vm.banner_es_advertencia)
        self._alerta.mostrar(vm.alerta)
        self._recuadro.mostrar(vm.etiqueta, vm.detalle_cajon)

        codigo = vm.codigo_qr
        self._tarjeta_qr.visible = codigo is not None
        if codigo is not None and codigo != self._codigo_mostrado:
            self._qr.content = ft.Image(src=qr_png(codigo), fit=ft.BoxFit.CONTAIN,
                                        filter_quality=ft.FilterQuality.NONE)
            self._codigo_mostrado = codigo
        self._icono_conexion.icon = ft.Icons.WIFI if vm.conectado else ft.Icons.WIFI_OFF
        color_conexion = theme.VERDE_AZULADO if vm.conectado else theme.TEXTO_SECUNDARIO
        self._icono_conexion.color = color_conexion
        self._texto_conexion.value = vm.texto_conexion
        self._texto_conexion.color = color_conexion
        self._chip_conexion.bgcolor = theme.SELECCION_FONDO if vm.conectado else "#2a2a2a"

        cronometro = vm.cronometro
        self._tarjeta_tiempo.visible = cronometro is not None
        if cronometro is not None:
            titulo, detalle, tiempo, en_alerta = cronometro
            self._titulo_tiempo.value = titulo
            self._detalle_tiempo.value = detalle or ""
            self._detalle_tiempo.visible = detalle is not None
            self._tiempo.value = tiempo
            self._tiempo.color = theme.NARANJA if en_alerta else theme.TEXTO

        self._nota_uso.visible = vm.en_uso
        self._nota_uso.controls[1].value = vm.nota_uso
        aviso = vm.aviso_fin
        self._aviso_fin.visible = aviso is not None
        if aviso is not None:
            self._titulo_aviso.value, self._detalle_aviso.value = aviso
        self._extender.content = "Extendiendo…" if vm.procesando else "Extender 1 hora"
        filas = vm.filas_uso
        self._tabla_uso.visible = bool(filas)
        if filas != self._filas_mostradas:
            # Solo se reconstruye si cambió (p. ej. tras extender), no en cada segundo.
            self._tabla_uso.content = tabla_detalle(filas) if filas else None
            self._filas_mostradas = filas

        self._cancelar.visible = vm.puede_cancelar
        self._salida.visible = vm.en_uso
        for boton in (self._cancelar, self._salida, self._salida_aviso, self._extender):
            boton.disabled = vm.procesando
        self._cancelar.content = "Cancelando…" if vm.procesando else "Cancelar reserva"

    def _sincronizar_hoja(self) -> None:
        textos = self._vm.texto_confirmacion
        if textos is not None:
            titulo, detalle, boton = textos
            self._titulo_hoja.value = titulo
            self._detalle_hoja.value = detalle
            peligro = self._vm.confirmacion == Confirmacion.CANCELAR
            self._confirmar_peligro.visible = peligro
            self._confirmar_normal.visible = not peligro
            self._confirmar_peligro.content = boton
            self._confirmar_normal.content = boton
        abrir = textos is not None
        if abrir == self._hoja_abierta:
            return
        if abrir:
            pagina = self._pagina()
            if pagina is not None:
                pagina.show_dialog(self._hoja)
                self._hoja_abierta = True
        else:
            self._cerrar_hoja()

    def _cerrar_hoja(self) -> None:
        self._hoja_abierta = False
        pagina = self._pagina()
        if pagina is not None:
            try:
                pagina.pop_dialog()
            except Exception:
                logger.debug("La hoja de confirmación ya estaba cerrada")

    def _pagina(self) -> ft.Page | None:
        try:
            return self.view.page
        except RuntimeError:
            return None

    # --- View -> ViewModel ---

    async def _on_regresar(self, _e: ft.Event) -> None:
        await self._vm.regresar()

    def _on_cancelar(self, _e: ft.Event) -> None:
        self._vm.pedir_cancelar()

    def _on_salida(self, _e: ft.Event) -> None:
        self._vm.pedir_salida()

    async def _on_extender(self, _e: ft.Event) -> None:
        await self._vm.extender()

    async def _on_confirmar(self, _e: ft.Event) -> None:
        await self._vm.confirmar_accion()

    def _on_mantener(self, _e: ft.Event) -> None:
        self._vm.descartar_confirmacion()

    def _on_hoja_cerrada(self, _e: ft.Event) -> None:
        # Cerrada al tocar fuera o arrastrarla: equivale a "Mantener reserva".
        self._hoja_abierta = False
        self._vm.descartar_confirmacion()

    async def _on_resultado(self, _e: ft.Event) -> None:
        await self._vm.accion_resultado()
