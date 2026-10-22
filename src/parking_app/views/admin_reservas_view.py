import flet as ft

from parking_app.core import theme
from parking_app.viewmodels.admin_reservas_viewmodel import (
    AdminReservasViewModel,
    FaseAdmin,
    FilaReserva,
)
from parking_app.views.components.formulario import (
    BannerAlerta,
    actualizar,
    barra_titulo,
    boton_principal,
    nota_informativa,
    titulo_seccion,
)

RUTA = "/admin/reservas"

_RESERVADO = theme.colores_estado("reservado")
_OCUPADO = theme.colores_estado("ocupado")
# Número más claro que el borde para que se lea sobre el fondo oscuro.
_AZUL_TEXTO = "#8C9EFF"

# (fondo, borde, color del texto) de cada contador y de la insignia del cajón.
COLORES_FASE: dict[FaseAdmin, tuple[str, str, str]] = {
    FaseAdmin.POR_LLEGAR: (_RESERVADO.fondo, _RESERVADO.acento, _AZUL_TEXTO),
    FaseAdmin.EN_TOLERANCIA: (theme.ALERTA_FONDO, theme.NARANJA, theme.NARANJA),
    FaseAdmin.EN_USO: (_OCUPADO.fondo, _OCUPADO.acento, _OCUPADO.acento),
}
# Insignia del cajón: azul mientras está reservado (por llegar o en tolerancia), rojo en uso.
BORDE_INSIGNIA = {
    FaseAdmin.POR_LLEGAR: _RESERVADO,
    FaseAdmin.EN_TOLERANCIA: _RESERVADO,
    FaseAdmin.EN_USO: _OCUPADO,
}


class _Contador:
    def __init__(self, fase: FaseAdmin, etiqueta: str) -> None:
        fondo, borde, color = COLORES_FASE[fase]
        self.numero = ft.Text("0", size=26, weight=ft.FontWeight.BOLD, color=color)
        self.control = ft.Container(
            expand=True,
            height=78,
            border_radius=12,
            bgcolor=fondo,
            border=ft.Border.all(1, borde),
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                tight=True,
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[self.numero,
                          ft.Text(etiqueta, size=12, weight=ft.FontWeight.W_600, color=color)],
            ),
        )


def _fila(fila: FilaReserva) -> ft.Container:
    insignia = BORDE_INSIGNIA[fila.fase]
    color_tiempo = theme.NARANJA if fila.fase == FaseAdmin.EN_TOLERANCIA else theme.TEXTO
    return ft.Container(
        bgcolor=theme.SUPERFICIE_ELEVADA,
        border=ft.Border.all(1, theme.BORDE_CAMPO),
        border_radius=16,
        padding=ft.Padding.symmetric(vertical=14, horizontal=14),
        content=ft.Row(
            spacing=14,
            controls=[
                ft.Container(
                    width=56,
                    height=56,
                    border_radius=12,
                    bgcolor=insignia.fondo,
                    border=ft.Border.all(2, insignia.acento),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text(fila.etiqueta, size=17, weight=ft.FontWeight.BOLD,
                                    color=theme.TEXTO),
                ),
                ft.Column(
                    expand=True,
                    spacing=2,
                    controls=[
                        ft.Text(fila.titulo, size=15, weight=ft.FontWeight.W_700,
                                color=theme.TEXTO),
                        ft.Text(fila.detalle, size=12, color=theme.TEXTO_SECUNDARIO),
                    ],
                ),
                ft.Text(fila.tiempo, size=17, weight=ft.FontWeight.BOLD, color=color_tiempo),
            ],
        ),
    )


# Clase representativa de "Reservas" (administrador): contadores, reservas
# vigentes con sus tiempos y el acceso al escáner.
class AdminReservasView:
    def __init__(self, vm: AdminReservasViewModel) -> None:
        self._vm = vm
        self._contadores = {
            FaseAdmin.POR_LLEGAR: _Contador(FaseAdmin.POR_LLEGAR, "Por llegar"),
            FaseAdmin.EN_TOLERANCIA: _Contador(FaseAdmin.EN_TOLERANCIA, "En tolerancia"),
            FaseAdmin.EN_USO: _Contador(FaseAdmin.EN_USO, "En uso"),
        }
        self._alerta = BannerAlerta()
        self._lista = ft.Column(spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self._vacia = ft.Container(
            visible=False,
            bgcolor=theme.SUPERFICIE_ELEVADA,
            border=ft.Border.all(1, theme.BORDE_CAMPO),
            border_radius=16,
            padding=ft.Padding.symmetric(vertical=24, horizontal=16),
            content=ft.Text("No hay reservas activas en este momento.", size=14,
                            color=theme.TEXTO_SECUNDARIO, text_align=ft.TextAlign.CENTER),
        )
        self._cargando = ft.Container(
            alignment=ft.Alignment.CENTER,
            padding=24,
            content=ft.ProgressRing(width=32, height=32, color=theme.VERDE_AZULADO),
        )
        insignia_admin = ft.Container(
            bgcolor=theme.CASETA_FONDO,
            border=ft.Border.all(1, theme.AZUL),
            border_radius=12,
            padding=ft.Padding.symmetric(vertical=4, horizontal=12),
            content=ft.Text("Administrador", size=12, weight=ft.FontWeight.W_700,
                            color=theme.AZUL_CLARO),
        )
        self._escanear = boton_principal("Escanear código QR", self._on_escanear)
        self._escanear.icon = ft.Icons.QR_CODE_SCANNER

        self.view = ft.View(
            route=RUTA,
            bgcolor=theme.FONDO,
            padding=ft.Padding.symmetric(horizontal=24, vertical=16),
            controls=[
                ft.SafeArea(
                    expand=True,
                    content=ft.Column(
                        expand=True,
                        spacing=16,
                        controls=[
                            barra_titulo("Reservas", self._on_regresar),
                            ft.Column(
                                expand=True,
                                scroll=ft.ScrollMode.AUTO,
                                spacing=16,
                                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                controls=[
                                    ft.Row(controls=[insignia_admin]),
                                    ft.Row(spacing=10, controls=[
                                        c.control for c in self._contadores.values()]),
                                    self._alerta.control,
                                    titulo_seccion("Reservas activas"),
                                    self._cargando,
                                    self._vacia,
                                    self._lista,
                                    nota_informativa(
                                        ft.Icons.INFO_OUTLINE,
                                        "Los tiempos se actualizan en vivo. Una reserva en "
                                        "tolerancia se cancela sola si el estudiante no llega.",
                                    ),
                                ],
                            ),
                            ft.Row(controls=[self._escanear]),
                            ft.Container(height=4),
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
        for fase, contador in self._contadores.items():
            contador.numero.value = str(vm.contar(fase))
        self._alerta.mostrar(vm.alerta)
        self._cargando.visible = vm.cargando
        self._vacia.visible = vm.vacia and vm.alerta is None
        self._lista.controls = [_fila(f) for f in vm.filas]

    # --- View -> ViewModel ---

    async def _on_regresar(self, _e: ft.Event) -> None:
        await self._vm.regresar()

    async def _on_escanear(self, _e: ft.Event) -> None:
        await self._vm.escanear()
