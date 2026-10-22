import asyncio
import logging

import flet as ft

from parking_app.core import theme
from parking_app.viewmodels.escaner_viewmodel import EscanerViewModel, FaseEscaner, Resultado
from parking_app.views.components.formulario import (
    BannerAlerta,
    CampoFormulario,
    RecuadroCajon,
    actualizar,
    boton_contorno,
    boton_principal,
    boton_regresar,
    tabla_detalle,
)

logger = logging.getLogger(__name__)

RUTA = "/admin/escanear"

LADO_GUIA = 240
ROJO_FONDO = "#3B1411"
ROJO_TEXTO = "#F28B82"
ROJO_DETALLE = "#F3CDC8"


def _esquina(top: bool, left: bool) -> ft.Container:
    """Una esquina redondeada del recuadro guía.

    Flutter no redondea un borde que solo tiene dos lados: se recorta la esquina
    de un cuadro redondeado completo del doble de tamaño.
    """
    lado = 48
    return ft.Container(
        width=lado,
        height=lado,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Stack(controls=[
            ft.Container(
                left=0 if left else -lado, top=0 if top else -lado,
                width=lado * 2, height=lado * 2, border_radius=16,
                border=ft.Border.all(4, theme.AZUL_CLARO),
            ),
        ]),
    )


def _guia() -> ft.Container:
    """Recuadro con esquinas azules y la línea naranja de escaneo (como el mockup)."""
    return ft.Container(
        width=LADO_GUIA,
        height=LADO_GUIA,
        content=ft.Stack(controls=[
            ft.Container(left=0, top=0, content=_esquina(True, True)),
            ft.Container(right=0, top=0, content=_esquina(True, False)),
            ft.Container(left=0, bottom=0, content=_esquina(False, True)),
            ft.Container(right=0, bottom=0, content=_esquina(False, False)),
            ft.Container(
                left=16, right=16, top=LADO_GUIA / 2 - 1.5, height=3,
                bgcolor=theme.NARANJA, border_radius=2,
                shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.with_opacity(0.7,
                                                                                  theme.NARANJA)),
            ),
        ]),
    )


def _circulo(valido: bool) -> ft.Container:
    color = theme.VERDE_AZULADO if valido else theme.COLOR_ERROR
    return ft.Container(
        width=100,
        height=100,
        border_radius=50,
        bgcolor=theme.SELECCION_FONDO if valido else ROJO_FONDO,
        border=ft.Border.all(2, color),
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(ft.Icons.CHECK_ROUNDED if valido else ft.Icons.CLOSE_ROUNDED, size=46,
                        color=color if valido else ROJO_TEXTO),
    )


def _motivo(titulo: str, detalle: str) -> ft.Container:
    return ft.Container(
        bgcolor=ROJO_FONDO,
        border=ft.Border.all(1, theme.COLOR_ERROR),
        border_radius=14,
        padding=ft.Padding.symmetric(vertical=14, horizontal=16),
        content=ft.Column(spacing=4, controls=[
            ft.Text("MOTIVO", size=11, weight=ft.FontWeight.BOLD, color=ROJO_TEXTO),
            ft.Text(titulo, size=18, weight=ft.FontWeight.BOLD, color=theme.TEXTO),
            ft.Text(detalle, size=13, color=ROJO_DETALLE),
        ]),
    )


# Clase representativa de "Escanear QR" (administrador): cámara con guía,
# linterna, "Validando código…" y el resultado (válido o rechazado con motivo).
class EscanerView:
    def __init__(self, vm: EscanerViewModel, con_camara: bool) -> None:
        self._vm = vm
        self._con_camara = con_camara
        self._camara = None
        self._permisos = None
        self._camara_lista = False
        self._transmitiendo = False
        self._linterna_activa = False
        self._sincronizando = False
        self._tareas: set[asyncio.Task[None]] = set()

        self._titulo = ft.Text(size=24, weight=ft.FontWeight.BOLD, color=theme.TEXTO,
                               expand=True)
        barra = ft.Row(spacing=14, controls=[boton_regresar(self._on_regresar), self._titulo])

        # --- Escaneo ---
        self._alerta = BannerAlerta()
        if con_camara:
            import flet_camera as fc  # solo existe en el teléfono (Android/iOS)

            self._camara = fc.Camera(expand=True, on_stream_image=self._on_cuadro,
                                     on_state_change=self._on_estado_camara)
            vista_previa: ft.Control = self._camara
        else:
            vista_previa = ft.Container(expand=True, bgcolor="#1B2523")
        self._texto_linterna = ft.Text("Encender linterna", size=15, weight=ft.FontWeight.W_700,
                                       color=theme.TEXTO)
        self._icono_linterna = ft.Icon(ft.Icons.FLASH_ON_OUTLINED, size=20, color=theme.TEXTO)
        self._linterna = ft.Container(
            visible=con_camara,
            height=54,
            border_radius=theme.RADIO_CAMPO,
            bgcolor=theme.SUPERFICIE_ELEVADA,
            border=ft.Border.all(1, theme.BORDE_CAMPO),
            alignment=ft.Alignment.CENTER,
            on_click=self._on_linterna,
            content=ft.Row(tight=True, spacing=10,
                           controls=[self._icono_linterna, self._texto_linterna]),
        )
        # En la PC no hay cámara (flet-camera solo funciona en Android/iOS): se
        # escribe el código para poder probar la validación.
        self._codigo_manual = CampoFormulario("Código de la reserva", on_change=lambda _: None,
                                              icono=ft.Icons.QR_CODE_2)
        self._manual = ft.Column(
            visible=not con_camara,
            spacing=12,
            controls=[
                ft.Text("La cámara solo está disponible en el teléfono. En la computadora "
                        "escribe el código para probar la validación.", size=13,
                        color=theme.NARANJA),
                self._codigo_manual.control,
                ft.Row(controls=[boton_principal("Validar código", self._on_validar_manual)]),
            ],
        )
        self._escaneo = ft.Column(
            expand=True,
            spacing=16,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                self._alerta.control,
                ft.Container(
                    expand=True,
                    border_radius=24,
                    bgcolor="#1B2523",
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    content=ft.Stack(expand=True, controls=[
                        ft.Container(left=0, right=0, top=0, bottom=0, content=vista_previa),
                        ft.Container(left=0, right=0, top=0, bottom=0,
                                     alignment=ft.Alignment.CENTER, content=_guia()),
                        ft.Container(
                            left=16, right=16, bottom=20,
                            content=ft.Text("Centra el código QR del estudiante dentro del "
                                            "recuadro", size=13, color=theme.TEXTO,
                                            text_align=ft.TextAlign.CENTER),
                        ),
                    ]),
                ),
                self._linterna,
                self._manual,
            ],
        )

        # --- Validando ---
        self._validando = ft.Container(
            visible=False,
            expand=True,
            bgcolor=theme.FONDO,
            content=ft.Column(
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Container(
                        expand=True,
                        alignment=ft.Alignment.CENTER,
                        content=ft.Column(
                            tight=True,
                            spacing=18,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.ProgressRing(width=88, height=88, stroke_width=8,
                                                color=theme.AZUL_CLARO,
                                                bgcolor=theme.BORDE_CAMPO),
                                ft.Container(height=6),
                                ft.Text("Validando código…", size=24, weight=ft.FontWeight.BOLD,
                                        color=theme.TEXTO),
                                ft.Text("Esto tarda solo unos segundos. No cierres la pantalla.",
                                        size=14, color=theme.TEXTO_SECUNDARIO,
                                        text_align=ft.TextAlign.CENTER),
                            ],
                        ),
                    ),
                    ft.Row(controls=[boton_contorno("Cancelar", self._on_cancelar)]),
                    ft.Container(height=4),
                ],
            ),
        )

        # --- Resultado ---
        self._contenido_resultado = ft.Column(
            spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        boton_otro = boton_principal("Escanear otro código", self._on_escanear_otro)
        boton_otro.icon = ft.Icons.QR_CODE_SCANNER
        self._resultado = ft.Container(
            visible=False,
            expand=True,
            bgcolor=theme.FONDO,
            content=ft.Column(
                expand=True,
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    ft.Column(expand=True, scroll=ft.ScrollMode.AUTO,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                              controls=[self._contenido_resultado]),
                    ft.Row(controls=[boton_otro]),
                    ft.Row(controls=[boton_contorno("Ver reservas", self._on_ver_reservas)]),
                    ft.Container(height=4),
                ],
            ),
        )
        self._resultado_mostrado: Resultado | None = None

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
                            barra,
                            # La cámara queda montada debajo: no se reinicia entre lecturas.
                            ft.Stack(expand=True, controls=[
                                self._escaneo, self._validando, self._resultado]),
                        ],
                    ),
                )
            ],
        )
        self._render()

    # --- Ciclo de vida (lo invoca el router) ---

    def montar(self) -> None:
        self._vm.add_listener(self._on_cambio)
        if self._camara is not None:
            self._en_segundo_plano(self._preparar_camara())

    def desmontar(self) -> None:
        self._vm.remove_listener(self._on_cambio)
        self._vm.cancelar_validacion()
        if self._transmitiendo:
            self._en_segundo_plano(self._detener_transmision())

    # --- ViewModel -> View ---

    def _on_cambio(self) -> None:
        self._render()
        actualizar(self.view)
        if self._camara is not None and self._camara_lista:
            self._en_segundo_plano(self._sincronizar_camara())

    def _render(self) -> None:
        vm = self._vm
        self._titulo.value = vm.titulo
        self._alerta.mostrar(vm.alerta)
        self._validando.visible = vm.fase == FaseEscaner.VALIDANDO
        self._resultado.visible = vm.fase == FaseEscaner.RESULTADO
        encendida = vm.linterna
        self._texto_linterna.value = "Apagar linterna" if encendida else "Encender linterna"
        self._icono_linterna.icon = ft.Icons.FLASH_OFF if encendida else ft.Icons.FLASH_ON_OUTLINED
        self._icono_linterna.color = theme.NARANJA if encendida else theme.TEXTO
        if vm.resultado is not None and vm.resultado is not self._resultado_mostrado:
            self._contenido_resultado.controls = self._construir_resultado(vm.resultado)
            self._resultado_mostrado = vm.resultado

    @staticmethod
    def _construir_resultado(r: Resultado) -> list[ft.Control]:
        controles: list[ft.Control] = [
            ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[_circulo(r.valido)]),
            ft.Text(r.titulo, size=26, weight=ft.FontWeight.BOLD, color=theme.TEXTO,
                    text_align=ft.TextAlign.CENTER),
            ft.Text(r.subtitulo, size=14, color=theme.TEXTO_SECUNDARIO,
                    text_align=ft.TextAlign.CENTER),
            ft.Container(height=4),
        ]
        if r.cajon is not None:
            recuadro = RecuadroCajon("reservado")
            recuadro.mostrar(*r.cajon)
            controles.append(recuadro.control)
        if r.motivo is not None:
            controles.append(_motivo(*r.motivo))
        if r.filas:
            controles.append(tabla_detalle(r.filas, r.fila_destacada))
        return controles

    # --- Cámara (flet-camera) ---

    def _en_segundo_plano(self, corrutina) -> None:
        try:
            tarea = asyncio.get_running_loop().create_task(corrutina)
        except RuntimeError:
            corrutina.close()
            return
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)

    async def _preparar_camara(self) -> None:
        import flet_camera as fc
        import flet_permission_handler as fph

        try:
            self._permisos = self._permisos or fph.PermissionHandler()
            estado = await self._permisos.request(fph.Permission.CAMERA)
            if estado != fph.PermissionStatus.GRANTED:
                self._vm.error_camara("Permite el acceso a la cámara en los ajustes del teléfono.")
                if estado == fph.PermissionStatus.PERMANENTLY_DENIED:
                    await self._permisos.open_app_settings()
                return
            camaras = await self._camara.get_available_cameras()
            if not camaras:
                self._vm.error_camara("No se encontró ninguna cámara.")
                return
            trasera = next((c for c in camaras
                            if c.lens_direction == fc.CameraLensDirection.BACK), camaras[0])
            # Resolución media: la prueba en Android leyó en ≈ 1.7 s (alta es más lenta).
            await self._camara.initialize(trasera, fc.ResolutionPreset.MEDIUM, enable_audio=False)
            self._camara_lista = True
            await self._sincronizar_camara()
        except Exception as e:
            logger.exception("No se pudo iniciar la cámara")
            self._vm.error_camara(f"{type(e).__name__}: {e}")

    async def _sincronizar_camara(self) -> None:
        """Lleva la cámara al estado que pide el ViewModel (transmitir y linterna)."""
        if self._sincronizando:
            return
        self._sincronizando = True
        try:
            import flet_camera as fc

            # Se repite si el ViewModel cambió mientras se esperaba a la cámara.
            while (self._vm.escaneando != self._transmitiendo
                   or self._vm.linterna != self._linterna_activa):
                if self._vm.escaneando and not self._transmitiendo:
                    await self._camara.resume_preview()
                    await self._camara.start_image_stream()
                    self._transmitiendo = True
                elif not self._vm.escaneando and self._transmitiendo:
                    await self._detener_transmision()
                    await self._camara.pause_preview()
                if self._vm.linterna != self._linterna_activa:
                    linterna = self._vm.linterna
                    await self._camara.set_flash_mode(
                        fc.FlashMode.TORCH if linterna else fc.FlashMode.OFF)
                    self._linterna_activa = linterna
        except Exception as e:
            logger.exception("Fallo al controlar la cámara")
            self._vm.error_camara(f"{type(e).__name__}: {e}")
        finally:
            self._sincronizando = False

    async def _detener_transmision(self) -> None:
        self._transmitiendo = False
        try:
            await self._camara.stop_image_stream()
        except Exception:
            logger.debug("stop_image_stream falló (cámara ya cerrada)", exc_info=True)

    async def _on_cuadro(self, e) -> None:
        await self._vm.procesar_cuadro(e.bytes)

    def _on_estado_camara(self, e) -> None:
        if getattr(e, "has_error", False):
            self._vm.error_camara(e.error_description or "Error de la cámara")

    # --- View -> ViewModel ---

    async def _on_regresar(self, _e: ft.Event) -> None:
        await self._vm.regresar()

    def _on_linterna(self, _e: ft.Event) -> None:
        self._vm.alternar_linterna()

    async def _on_validar_manual(self, _e: ft.Event) -> None:
        await self._vm.validar(self._codigo_manual.campo.value or "")

    def _on_cancelar(self, _e: ft.Event) -> None:
        self._vm.cancelar_validacion()

    def _on_escanear_otro(self, _e: ft.Event) -> None:
        self._codigo_manual.campo.value = ""
        self._vm.escanear_otro()

    async def _on_ver_reservas(self, _e: ft.Event) -> None:
        await self._vm.ver_reservas()
