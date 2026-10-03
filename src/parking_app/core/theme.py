"""Paleta y tema visual de la app."""

from dataclasses import dataclass

import flet as ft

# Paleta base
AZUL = "#2B9AC7"
AZUL_CLARO = "#5EBEE0"
NARANJA = "#F2A83B"
VERDE_AZULADO = "#1D9E8C"
VERDE_OSCURO = "#0B6E5C"

COLOR_ERROR = "#ef4444"

# Superficies y texto (modo oscuro de los mockups)
FONDO = "#0F1716"
SUPERFICIE_CAMPO = "#141D1C"
SUPERFICIE_ELEVADA = "#172120"
SELECCION_FONDO = "#12332D"

# Mapa de ocupación
MAPA_FONDO = "#141C1B"
CASETA_FONDO = "#0E3240"
ZONA_FONDO = "#0F2A26"
ZONA_BORDE = "#2A6B5F"
ZONA_TEXTO = "#9FD3C7"
BARRA_INFERIOR = "#131A19"

# Fondos claros de los íconos destacados (recuperar contraseña)
ICONO_AZUL_FONDO = "#DCEFF7"
ICONO_VERDE_FONDO = "#DDF3EC"
BORDE_CAMPO = "#2C3836"
TEXTO = "#F1F5F4"
TEXTO_SECUNDARIO = "#A3AEAC"
TEXTO_TENUE = "#7D8987"

# Banner de advertencia (acento = NARANJA)
ALERTA_FONDO = "#3A2A12"
ALERTA_BORDE = "#8A6A2E"
ALERTA_TEXTO = "#E6D5B8"

RADIO_CAMPO = 12


@dataclass(frozen=True)
class ColoresEstado:
    fondo: str
    acento: str


# Estados de cajón (fondo / acento). Claves = valores de EstadoCajon.
COLORES_ESTADO_CAJON: dict[str, ColoresEstado] = {
    "libre": ColoresEstado(fondo="#1a2e1a", acento="#4ade80"),
    "ocupado": ColoresEstado(fondo="#2e1a1a", acento="#ef4444"),
    "no conectado": ColoresEstado(fondo="#2a2a2a", acento="#9ca3af"),
    "reservado": ColoresEstado(fondo="#1e1a2e", acento="#305CDE"),
}


def colores_estado(estado: str) -> ColoresEstado:
    return COLORES_ESTADO_CAJON.get(estado, COLORES_ESTADO_CAJON["no conectado"])


def crear_tema() -> ft.Theme:
    return ft.Theme(color_scheme_seed=VERDE_AZULADO, use_material3=True)
