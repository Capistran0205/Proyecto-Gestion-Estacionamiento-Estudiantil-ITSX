"""Piezas visuales compartidas por las pantallas de acceso (login, registro, recuperar)."""

from collections.abc import Callable, Sequence
from typing import Any

import flet as ft

from parking_app.core import theme
from parking_app.core.validadores import PATRON_CARACTER_NOMBRE
from parking_app.viewmodels.alerta import Alerta

Handler = Callable[[Any], Any]


def filtro_nombre() -> ft.InputFilter:
    """Rechaza al escribir (o pegar) todo lo que no sea válido en un nombre.

    Flet evalúa el texto completo tras cada cambio y, si no coincide, conserva el
    anterior. Por eso el patrón va anclado (^…$, como NumbersOnlyInputFilter) y
    con `*`, para que el campo vacío también sea válido y se pueda borrar todo.
    """
    return ft.InputFilter(regex_string=rf"^{PATRON_CARACTER_NOMBRE}*$", allow=True)


def encabezado(titulo: str, subtitulo: str) -> ft.Column:
    logo = ft.Container(
        width=76,
        height=76,
        border_radius=18,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT,
            end=ft.Alignment.BOTTOM_RIGHT,
            colors=[theme.VERDE_AZULADO, theme.VERDE_OSCURO],
        ),
        alignment=ft.Alignment.CENTER,
        content=ft.Text("P", size=42, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
    )
    return ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=6,
        controls=[
            logo,
            ft.Container(height=10),
            ft.Text(
                titulo,
                size=24,
                weight=ft.FontWeight.BOLD,
                color=theme.TEXTO,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Text(
                subtitulo,
                size=14,
                color=theme.TEXTO_SECUNDARIO,
                text_align=ft.TextAlign.CENTER,
            ),
        ],
    )


def boton_regresar(on_click: Handler) -> ft.Container:
    return ft.Container(
        width=44,
        height=44,
        border_radius=12,
        border=ft.Border.all(1, theme.BORDE_CAMPO),
        bgcolor=theme.SUPERFICIE_CAMPO,
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(ft.Icons.CHEVRON_LEFT, color=theme.TEXTO, size=22),
        on_click=on_click,
        tooltip="Regresar",
    )


def encabezado_pagina(titulo: str, subtitulo: str, on_regresar: Handler) -> ft.Column:
    """Botón de regresar + título alineado a la izquierda (pantallas secundarias)."""
    return ft.Column(
        spacing=8,
        controls=[
            ft.Row(controls=[boton_regresar(on_regresar)]),
            ft.Container(height=8),
            ft.Text(titulo, size=28, weight=ft.FontWeight.BOLD, color=theme.TEXTO),
            ft.Text(subtitulo, size=14, color=theme.TEXTO_SECUNDARIO),
        ],
    )


class IndicadorPasos:
    """Botón de regresar + "Paso n de N" + barra segmentada de progreso."""

    def __init__(self, total: int, on_regresar: Handler) -> None:
        self._texto = ft.Text(size=14, color=theme.TEXTO_SECUNDARIO)
        self._segmentos = [
            ft.Container(expand=True, height=4, border_radius=2, bgcolor=theme.BORDE_CAMPO)
            for _ in range(total)
        ]
        self._total = total
        self.control = ft.Column(
            spacing=20,
            controls=[
                ft.Row(spacing=14, controls=[boton_regresar(on_regresar), self._texto]),
                ft.Row(spacing=6, controls=self._segmentos),
            ],
        )

    @property
    def texto(self) -> str:
        return self._texto.value

    def sincronizar(self, paso: int) -> None:
        self._texto.value = f"Paso {paso} de {self._total}"
        for i, segmento in enumerate(self._segmentos, start=1):
            segmento.bgcolor = theme.VERDE_AZULADO if i <= paso else theme.BORDE_CAMPO


def icono_destacado(icono: ft.IconData, fondo: str, color: str) -> ft.Container:
    return ft.Container(
        width=56,
        height=56,
        border_radius=14,
        bgcolor=fondo,
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(icono, size=26, color=color),
    )


def boton_secundario(texto: str, icono: ft.IconData, on_click: Handler) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        content=texto,
        icon=icono,
        icon_color=theme.AZUL_CLARO,
        height=54,
        expand=True,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=theme.RADIO_CAMPO),
            side=ft.BorderSide(1.5, theme.AZUL_CLARO),
            color=theme.AZUL_CLARO,
            text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_700),
        ),
        on_click=on_click,
    )

# Clase para construir la pantalla de éxito de registro del usuario o cambio de contraseña y destinada a redirigir al login del sistema
class PantallaExito:
    """Círculo con palomita + título + detalle, con el botón de acción al pie."""

    def __init__(self, titulo: str, texto_boton: str, on_click: Handler) -> None:
        self.detalle = ft.Text(
            size=15, color=theme.TEXTO_SECUNDARIO, text_align=ft.TextAlign.CENTER
        )
        self.control = ft.Column(
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
                                bgcolor=theme.SELECCION_FONDO,
                                border=ft.Border.all(2, theme.VERDE_AZULADO),
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(
                                    ft.Icons.CHECK_ROUNDED, size=44, color=theme.VERDE_AZULADO
                                ),
                            ),
                            ft.Container(height=4),
                            ft.Text(
                                titulo,
                                size=26,
                                weight=ft.FontWeight.BOLD,
                                color=theme.TEXTO,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            self.detalle,
                        ],
                    ),
                ),
                ft.Row(controls=[boton_principal(texto_boton, on_click)]),
                ft.Container(height=8),
            ],
        )


def titulo_seccion(texto: str) -> ft.Text:
    return ft.Text(texto, size=16, weight=ft.FontWeight.W_600, color=theme.AZUL_CLARO)


def etiqueta(texto: str) -> ft.Text:
    return ft.Text(texto, size=14, weight=ft.FontWeight.W_600, color=theme.TEXTO)

# Clase representativa para mostrar errores en los formularios
class MensajeError:
    """Ícono + texto naranja debajo de un campo con error."""

    def __init__(self) -> None:
        self._texto = ft.Text(size=13, weight=ft.FontWeight.W_600, color=theme.NARANJA)
        self.control = ft.Row(
            visible=False,
            spacing=6,
            controls=[ft.Icon(ft.Icons.ERROR_OUTLINE, size=16, color=theme.NARANJA), self._texto],
        )

    @property
    def texto(self) -> str | None:
        return self._texto.value if self.control.visible else None

    def mostrar(self, error: str | None) -> None:
        self.control.visible = error is not None
        self._texto.value = error or ""

# Clase representativa para los campos de correo y contraseña con la etiqueta siempre visible, con un texto de ayuda y el mensaje de error debajo.
class CampoFormulario:
    """Etiqueta visible + campo (ícono opcional) + ayuda o error debajo.

    La etiqueta va fuera del campo para que no desaparezca al escribir.
    """

    def __init__(
        self,
        etiqueta_campo: str,
        on_change: Callable[[str], None],
        icono: ft.IconData | None = None,
        ayuda: str | None = None,
        password: bool = False,
        keyboard_type: ft.KeyboardType = ft.KeyboardType.TEXT,
        capitalization: ft.TextCapitalization | None = None,
        autofill: ft.AutofillHint | None = None,
        on_submit: Handler | None = None,
        input_filter: ft.InputFilter | None = None,
    ) -> None:
        self.campo = ft.TextField(
            input_filter=input_filter,
            password=password,
            can_reveal_password=password,
            keyboard_type=keyboard_type,
            capitalization=capitalization,
            autofill_hints=autofill,
            autocorrect=False,
            enable_suggestions=not password,
            prefix_icon=ft.Icon(icono, size=20, color=theme.TEXTO_TENUE) if icono else None,
            filled=True,
            fill_color=theme.SUPERFICIE_CAMPO,
            border_radius=theme.RADIO_CAMPO,
            border_color=theme.BORDE_CAMPO,
            focused_border_color=theme.VERDE_AZULADO,
            border_width=1,
            focused_border_width=1.5,
            color=theme.TEXTO,
            cursor_color=theme.VERDE_AZULADO,
            text_size=16,
            content_padding=ft.Padding.symmetric(vertical=16, horizontal=14),
            on_change=lambda e: on_change(e.control.value or ""),
            on_submit=on_submit,
        )
        self.texto_ayuda = ft.Text(
            ayuda or "", size=12, color=theme.TEXTO_SECUNDARIO, visible=ayuda is not None
        )
        self._tiene_ayuda = ayuda is not None
        self.error = MensajeError()
        self.control = ft.Column(
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[etiqueta(etiqueta_campo), self.campo, self.texto_ayuda, self.error.control],
        )

    def sincronizar(self, valor: str, error: str | None = None, resaltado: bool = False) -> None:
        # Solo se reasigna si cambió: reasignar mientras se escribe mueve el cursor.
        if (self.campo.value or "") != valor:
            self.campo.value = valor

        advertencia = error is not None or resaltado
        self.campo.border_color = theme.NARANJA if advertencia else theme.BORDE_CAMPO
        self.campo.focused_border_color = theme.NARANJA if advertencia else theme.VERDE_AZULADO
        self.error.mostrar(error)
        # El error sustituye a la ayuda para no apilar dos textos bajo el campo.
        self.texto_ayuda.visible = self._tiene_ayuda and error is None

# Clase para representar y construir el recuadro de aviso el cual se muestra cuando hay credenciales incorrectas, bloqueo con cuenta regresiva y fallas de conexión.
class BannerAlerta:
    """Recuadro de advertencia (ícono + título + detalle + acciones opcionales)."""

    def __init__(
        self, acciones: Sequence[tuple[str, Handler]] = (), con_icono: bool = True
    ) -> None:
        self._titulo = ft.Text(size=15, weight=ft.FontWeight.W_700, color=theme.TEXTO)
        self._detalle = ft.Text(size=13, color=theme.ALERTA_TEXTO)
        contenido: list[ft.Control] = [self._titulo, self._detalle]
        if acciones:
            contenido.append(
                ft.Row(
                    spacing=16,
                    wrap=True,
                    controls=[
                        ft.Container(
                            content=ft.Text(
                                texto, size=13, weight=ft.FontWeight.W_700, color=theme.NARANJA
                            ),
                            padding=ft.Padding.only(top=6, bottom=2),
                            on_click=on_click,
                        )
                        for texto, on_click in acciones
                    ],
                )
            )
        self.control = ft.Container(
            visible=False,
            bgcolor=theme.ALERTA_FONDO,
            border=ft.Border.all(1, theme.ALERTA_BORDE),
            border_radius=theme.RADIO_CAMPO,
            padding=ft.Padding.symmetric(vertical=14, horizontal=16),
            content=ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.START,
                spacing=12,
                controls=[
                    ft.Icon(
                        ft.Icons.WARNING_AMBER_ROUNDED,
                        color=theme.NARANJA,
                        size=24,
                        visible=con_icono,
                    ),
                    ft.Column(expand=True, spacing=4, controls=contenido),
                ],
            ),
        )

    @property
    def titulo(self) -> str | None:
        return self._titulo.value if self.control.visible else None

    def mostrar(self, alerta: Alerta | None) -> None:
        self.control.visible = alerta is not None
        if alerta is not None:
            self._titulo.value = alerta.titulo
            self._detalle.value = alerta.detalle or ""
            self._detalle.visible = alerta.detalle is not None

# Clase representativa para construir la elección del medio de transporte para el registro de un usuario, siendo como RadioButtons
class TarjetaOpcion:
    """Tarjeta seleccionable (ícono + texto + indicador tipo radio)."""

    def __init__(self, icono: ft.IconData, texto: str, on_click: Handler) -> None:
        self._icono = ft.Icon(icono, size=26, color=theme.TEXTO_SECUNDARIO)
        self._punto = ft.Container(width=10, height=10, border_radius=5, visible=False,
                                   bgcolor=theme.VERDE_OSCURO)
        self._radio = ft.Container(
            width=20,
            height=20,
            border_radius=10,
            bgcolor=ft.Colors.WHITE,
            alignment=ft.Alignment.CENTER,
            content=self._punto,
        )
        self.control = ft.Container(
            expand=True,
            height=114,
            border_radius=theme.RADIO_CAMPO,
            bgcolor=theme.SUPERFICIE_CAMPO,
            border=ft.Border.all(1, theme.BORDE_CAMPO),
            padding=ft.Padding.symmetric(vertical=14, horizontal=8),
            on_click=on_click,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
                controls=[
                    self._icono,
                    ft.Text(texto, size=15, weight=ft.FontWeight.W_700, color=theme.TEXTO),
                    self._radio,
                ],
            ),
        )

    @property
    def seleccionada(self) -> bool:
        return self._punto.visible

    def sincronizar(self, seleccionada: bool, resaltada: bool) -> None:
        if seleccionada:
            borde, fondo, color_icono = theme.VERDE_AZULADO, theme.SELECCION_FONDO, theme.VERDE_AZULADO
        elif resaltada:
            borde, fondo, color_icono = theme.NARANJA, theme.SUPERFICIE_CAMPO, theme.TEXTO_SECUNDARIO
        else:
            borde, fondo, color_icono = theme.BORDE_CAMPO, theme.SUPERFICIE_CAMPO, theme.TEXTO_SECUNDARIO
        self.control.border = ft.Border.all(1.5 if seleccionada or resaltada else 1, borde)
        self.control.bgcolor = fondo
        self._icono.color = color_icono
        self._punto.visible = seleccionada

# Clase representativa para construir el recuadro de los requisitos que debe tener la contraseña, siendo marcados al cumplirse cada uno.
class ListaRequisitos:
    """Recuadro "Tu contraseña debe tener:" con cada requisito marcado al cumplirse."""

    def __init__(self, textos: Sequence[str]) -> None:
        self._filas: list[tuple[ft.Icon, ft.Text]] = []
        filas: list[ft.Control] = []
        for texto in textos:
            icono = ft.Icon(ft.Icons.RADIO_BUTTON_UNCHECKED, size=18, color=theme.TEXTO_TENUE)
            etiqueta_req = ft.Text(texto, size=14, color=theme.TEXTO_SECUNDARIO, expand=True)
            self._filas.append((icono, etiqueta_req))
            filas.append(
                ft.Row(
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[icono, etiqueta_req],
                )
            )
        self.control = ft.Container(
            bgcolor=theme.SUPERFICIE_ELEVADA,
            border=ft.Border.all(1, theme.BORDE_CAMPO),
            border_radius=theme.RADIO_CAMPO,
            padding=ft.Padding.symmetric(vertical=14, horizontal=16),
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Text(
                        "Tu contraseña debe tener:",
                        size=13,
                        weight=ft.FontWeight.W_700,
                        color=theme.TEXTO,
                    ),
                    *filas,
                ],
            ),
        )

    def sincronizar(self, cumplidos: Sequence[bool]) -> None:
        for (icono, texto), ok in zip(self._filas, cumplidos, strict=True):
            icono.icon = ft.Icons.CHECK_CIRCLE_OUTLINE if ok else ft.Icons.RADIO_BUTTON_UNCHECKED
            icono.color = theme.VERDE_AZULADO if ok else theme.TEXTO_TENUE
            texto.color = theme.TEXTO if ok else theme.TEXTO_SECUNDARIO


def boton_principal(texto: str, on_click: Handler) -> ft.Button:
    return ft.Button(
        content=texto,
        height=54,
        expand=True,
        bgcolor=theme.VERDE_OSCURO,
        color=ft.Colors.WHITE,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=theme.RADIO_CAMPO),
            text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_700),
        ),
        on_click=on_click,
    )


def indicador_carga() -> ft.ProgressRing:
    return ft.ProgressRing(width=22, height=22, stroke_width=2.5, color=ft.Colors.WHITE)


def texto_con_enlace(texto: str, enlace_texto: str, on_click: Handler) -> ft.Text:
    """"¿No tienes cuenta? Regístrate" con solo la segunda parte clicable."""
    return ft.Text(
        text_align=ft.TextAlign.CENTER,
        spans=[
            ft.TextSpan(texto + " ", style=ft.TextStyle(size=14, color=theme.TEXTO_SECUNDARIO)),
            ft.TextSpan(
                enlace_texto,
                style=ft.TextStyle(size=14, color=theme.AZUL_CLARO, weight=ft.FontWeight.W_700),
                on_click=on_click,
            ),
        ],
    )


def enlace(texto: str, on_click: Handler) -> ft.TextButton:
    return ft.TextButton(
        content=ft.Text(texto, size=14, color=theme.AZUL_CLARO, weight=ft.FontWeight.W_600),
        style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=4, vertical=4)),
        on_click=on_click,
    )


def actualizar(control: ft.BaseControl) -> None:
    """update() tolerante: ignora el caso de una vista ya desmontada."""
    try:
        control.update()
    except RuntimeError:
        pass
