import logging

import flet as ft

from parking_app.core import theme
from parking_app.models.cajon_estacionamiento import EstadoCajon
from parking_app.viewmodels.ocupacion_viewmodel import TEXTOS_ESTADO
from parking_app.viewmodels.reservar_viewmodel import PasoReserva, ReservarViewModel
from parking_app.views.components.formulario import (
    BannerAlerta,
    CampoFormulario,
    MensajeError,
    ProgresoPasos,
    RecuadroCajon,
    actualizar,
    barra_titulo,
    boton_contorno,
    boton_principal,
    etiqueta,
    indicador_carga,
)
from parking_app.views.components.tarjeta_cajon import TarjetaCajon, leyenda_estados

logger = logging.getLogger(__name__)

RUTA = "/reservar"

# El paso 1 no muestra "Bloqueado" en la leyenda (como el mockup).
ESTADOS_LEYENDA = (
    EstadoCajon.LIBRE,
    EstadoCajon.OCUPADO,
    EstadoCajon.RESERVADO,
    EstadoCajon.NO_CONECTADO,
)


def _titulo(texto: str) -> ft.Text:
    return ft.Text(texto, size=24, weight=ft.FontWeight.BOLD, color=theme.TEXTO)


def _texto_secundario(texto: str) -> ft.Text:
    return ft.Text(texto, size=13, color=theme.TEXTO_SECUNDARIO)


class _FilaResumen:
    def __init__(self) -> None:
        self.etiqueta = ft.Text(size=14, color=theme.TEXTO_SECUNDARIO, expand=True)
        self.valor = ft.Text(size=14, weight=ft.FontWeight.BOLD, color=theme.TEXTO)
        self.control = ft.Container(
            padding=ft.Padding.symmetric(vertical=14, horizontal=16),
            content=ft.Row(controls=[self.etiqueta, self.valor]),
        )


# Clase representativa de "Reservar cajón": pasos 1 a 3 y el aviso de reserva activa.
class ReservarView:
    def __init__(self, vm: ReservarViewModel) -> None:
        self._vm = vm
        self._progreso = ProgresoPasos(vm.total_pasos)

        # --- Paso 1: elegir cajón ---
        self._banner_1 = BannerAlerta()
        self._tarjetas = [
            TarjetaCajon(c.etiqueta, on_click=self._al_tocar(c.etiqueta)) for c in vm.cajones
        ]
        self._recuadro_1 = RecuadroCajon()
        self._paso_1 = ft.Column(
            spacing=18,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Column(spacing=4, controls=[
                    _titulo("Elige un cajón libre"),
                    _texto_secundario("Solo puedes reservar los cajones marcados como libres."),
                ]),
                self._banner_1.control,
                leyenda_estados(ESTADOS_LEYENDA, TEXTOS_ESTADO),
                ft.Container(
                    bgcolor=theme.MAPA_FONDO,
                    border=ft.Border.all(1, theme.BORDE_CAMPO),
                    border_radius=20,
                    padding=14,
                    content=ft.Row(spacing=8, controls=[t.control for t in self._tarjetas]),
                ),
                self._recuadro_1.control,
            ],
        )

        # --- Paso 2: horario ---
        self._recuadro_2 = RecuadroCajon()
        self._banner_2 = BannerAlerta()
        self._inicio = CampoFormulario(
            "Hora de inicio",
            on_change=lambda _: None,
            icono=ft.Icons.LOCK_OUTLINE,
            ayuda="Se asigna automáticamente a la siguiente hora en punto y no se puede cambiar.",
        )
        self._inicio.campo.read_only = True
        self._inicio.campo.focused_border_color = theme.BORDE_CAMPO
        self._fin = ft.Dropdown(
            expand=True,
            leading_icon=ft.Icons.SCHEDULE,
            filled=True,
            fill_color=theme.SUPERFICIE_CAMPO,
            border_radius=theme.RADIO_CAMPO,
            border_color=theme.BORDE_CAMPO,
            color=theme.TEXTO,
            text_size=16,
            menu_height=320,
            on_select=self._on_fin,
        )
        self._error_fin = MensajeError()
        self._duracion = ft.Text(size=15, weight=ft.FontWeight.BOLD, color=theme.TEXTO)
        self._paso_2 = ft.Column(
            spacing=18,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                _titulo("Define tu horario"),
                self._recuadro_2.control,
                self._banner_2.control,
                self._inicio.control,
                ft.Column(
                    spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    controls=[
                        etiqueta("Hora de fin"),
                        ft.Row(controls=[self._fin]),
                        self._error_fin.control,
                        ft.Text(
                            "Debe ser el mismo día, dentro del horario del instituto y con una "
                            "duración máxima de 15 horas.",
                            size=12,
                            color=theme.TEXTO_SECUNDARIO,
                        ),
                    ],
                ),
                ft.Container(
                    bgcolor=theme.SUPERFICIE_ELEVADA,
                    border=ft.Border.all(1, theme.BORDE_CAMPO),
                    border_radius=theme.RADIO_CAMPO,
                    padding=ft.Padding.symmetric(vertical=16, horizontal=16),
                    content=ft.Row(controls=[
                        ft.Text("Duración de la reserva", size=14, color=theme.TEXTO_SECUNDARIO,
                                expand=True),
                        self._duracion,
                    ]),
                ),
            ],
        )

        # --- Paso 3: confirmar ---
        self._banner_3 = BannerAlerta()
        self._filas_resumen = [_FilaResumen() for _ in range(6)]
        resumen: list[ft.Control] = []
        for i, fila in enumerate(self._filas_resumen):
            if i:
                resumen.append(ft.Divider(height=1, color=theme.BORDE_CAMPO))
            resumen.append(fila.control)
        self._avisos = ft.Column(spacing=10)
        self._paso_3 = ft.Column(
            spacing=18,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                _titulo("Confirma tu reserva"),
                self._banner_3.control,
                ft.Container(
                    bgcolor=theme.SUPERFICIE_ELEVADA,
                    border=ft.Border.all(1, theme.BORDE_CAMPO),
                    border_radius=16,
                    content=ft.Column(spacing=0, controls=resumen),
                ),
                ft.Container(
                    bgcolor=theme.CASETA_FONDO,
                    border=ft.Border.all(1, theme.AZUL),
                    border_radius=16,
                    padding=ft.Padding.symmetric(vertical=16, horizontal=16),
                    content=ft.Column(spacing=12, controls=[
                        ft.Text("Antes de confirmar", size=15, weight=ft.FontWeight.BOLD,
                                color=theme.TEXTO),
                        self._avisos,
                    ]),
                ),
            ],
        )

        self._contenido = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[self._paso_1, self._paso_2, self._paso_3],
        )
        self._continuar = boton_principal("Continuar", self._on_continuar)
        self._cancelar = boton_contorno("Cancelar", self._on_cancelar)
        self._cargando = indicador_carga()
        self._flujo = ft.Column(
            expand=True,
            spacing=20,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                self._progreso.control,
                self._contenido,
                ft.Column(
                    spacing=12,
                    controls=[ft.Row(controls=[self._continuar]),
                              ft.Row(controls=[self._cancelar])],
                ),
            ],
        )

        # --- Ya tienes una reserva activa ---
        colores = theme.colores_estado("reservado")
        self._ver_reserva = boton_principal("Ver mi reserva", self._on_ver_reserva)
        self._reserva_activa = ft.Column(
            expand=True,
            visible=False,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Container(
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        tight=True,
                        spacing=16,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Container(
                                width=100,
                                height=100,
                                border_radius=50,
                                bgcolor=colores.fondo,
                                border=ft.Border.all(2, colores.acento),
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(ft.Icons.EVENT_AVAILABLE, size=40,
                                                color=theme.AZUL_CLARO),
                            ),
                            ft.Container(height=4),
                            ft.Text("Ya tienes una reserva activa", size=24,
                                    weight=ft.FontWeight.BOLD, color=theme.TEXTO,
                                    text_align=ft.TextAlign.CENTER),
                            ft.Text(
                                "Solo puedes tener una reserva a la vez. Consulta tu reserva "
                                "actual o cancélala para hacer una nueva.",
                                size=15, color=theme.TEXTO_SECUNDARIO,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                ),
                ft.Column(
                    spacing=12,
                    controls=[ft.Row(controls=[self._ver_reserva]),
                              ft.Row(controls=[boton_contorno("Volver", self._on_cancelar)])],
                ),
                ft.Container(height=8),
            ],
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
                            barra_titulo("Reservar cajón", self._on_regresar),
                            ft.Stack(expand=True, controls=[self._flujo, self._reserva_activa]),
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

    # --- ViewModel -> View ---

    def _on_cambio(self) -> None:
        self._render()
        actualizar(self.view)

    def _render(self) -> None:
        vm = self._vm
        self._flujo.visible = not vm.tiene_reserva_activa
        self._reserva_activa.visible = vm.tiene_reserva_activa
        self._ver_reserva.visible = vm.puede_ver_reserva
        if vm.tiene_reserva_activa:
            return

        paso = vm.paso
        self._progreso.sincronizar(vm.numero_paso)
        self._paso_1.visible = paso == PasoReserva.ELEGIR
        self._paso_2.visible = paso == PasoReserva.HORARIO
        self._paso_3.visible = paso == PasoReserva.CONFIRMAR
        for banner, paso_banner in (
            (self._banner_1, PasoReserva.ELEGIR),
            (self._banner_2, PasoReserva.HORARIO),
            (self._banner_3, PasoReserva.CONFIRMAR),
        ):
            banner.mostrar(vm.alerta if paso == paso_banner else None)

        if paso == PasoReserva.ELEGIR:
            for tarjeta, cajon in zip(self._tarjetas, vm.cajones, strict=True):
                tarjeta.sincronizar(
                    cajon.estado,
                    cajon.texto_estado,
                    tocable=cajon.tocable,
                    seleccionada=cajon.seleccionado,
                    atenuada=not (cajon.tocable or cajon.seleccionado),
                )
            self._recuadro_1.mostrar(vm.etiqueta, vm.subtitulo_cajon)
        elif paso == PasoReserva.HORARIO:
            self._recuadro_2.mostrar(vm.etiqueta, vm.subtitulo_cajon)
            self._inicio.sincronizar(vm.hora_inicio)
            self._fin.options = [ft.DropdownOption(key=k, text=t) for k, t in vm.opciones_fin]
            self._fin.value = vm.clave_fin
            advertencia = vm.error_fin is not None
            self._fin.border_color = theme.NARANJA if advertencia else theme.BORDE_CAMPO
            self._error_fin.mostrar(vm.error_fin)
            self._duracion.value = vm.duracion
        else:
            for fila, (nombre, valor) in zip(self._filas_resumen, vm.resumen, strict=False):
                fila.etiqueta.value = nombre
                fila.valor.value = valor
            self._avisos.controls = [self._aviso(fragmentos) for fragmentos in vm.avisos]

        texto = "Confirmar reserva" if paso == PasoReserva.CONFIRMAR else "Continuar"
        self._continuar.content = self._cargando if vm.cargando else texto
        self._continuar.disabled = vm.cargando
        # En el paso 1 se sale con el botón de regresar (como el mockup).
        self._cancelar.visible = paso != PasoReserva.ELEGIR

    @staticmethod
    def _aviso(fragmentos: list[tuple[str, bool]]) -> ft.Row:
        return ft.Row(
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Icon(ft.Icons.INFO_OUTLINE, size=18, color=theme.AZUL_CLARO),
                ft.Text(
                    expand=True,
                    size=13,
                    color=theme.TEXTO_SECUNDARIO,
                    spans=[
                        ft.TextSpan(
                            texto,
                            style=ft.TextStyle(weight=ft.FontWeight.BOLD, color=theme.TEXTO)
                            if negritas else None,
                        )
                        for texto, negritas in fragmentos
                    ],
                ),
            ],
        )

    # --- View -> ViewModel ---

    def _al_tocar(self, etiqueta_cajon: str):
        async def manejar(_e: ft.Event) -> None:
            await self._vm.seleccionar(etiqueta_cajon)

        return manejar

    def _on_fin(self, e: ft.Event) -> None:
        if e.control.value:
            self._vm.set_fin(e.control.value)

    async def _on_continuar(self, _e: ft.Event) -> None:
        if self._vm.paso == PasoReserva.CONFIRMAR:
            await self._vm.confirmar()
        else:
            await self._vm.continuar()
        try:
            await self._contenido.scroll_to(offset=0, duration=300)
        except RuntimeError:
            logger.debug("Reserva sin montar; no se desplaza")

    async def _on_cancelar(self, _e: ft.Event) -> None:
        await self._vm.cancelar()

    async def _on_regresar(self, _e: ft.Event) -> None:
        await self._vm.regresar()

    async def _on_ver_reserva(self, _e: ft.Event) -> None:
        await self._vm.ver_reserva()
