import logging
from pathlib import Path

import flet as ft

from parking_app.core import theme
from parking_app.core.config import ConfigError, get_settings
from parking_app.router import Router
from parking_app.services.auth_service import AuthService
from parking_app.services.cajones_service import CajonesService
from parking_app.services.emqx_admin_service import EmqxAdminService
from parking_app.services.mqtt_service import MqttService

# Ruta absoluta: Flet resuelve "assets" relativo al script de arranque (main.py de la raíz).
ASSETS_DIR = Path(__file__).parent / "assets"
# Icono de ventana: solo aplica en Windows y exige formato .ico.
ICONO_VENTANA = ASSETS_DIR / "icon.ico"


async def main(page: ft.Page) -> None:
    page.title = "Estacionamiento Alumnos"
    if ICONO_VENTANA.exists():
        page.window.icon = str(ICONO_VENTANA)
    page.theme = theme.crear_tema()
    page.dark_theme = theme.crear_tema()
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = theme.FONDO

    try:
        settings = get_settings()
    except ConfigError as e:
        logging.error("Configuración incompleta: %s", e)
        page.add(
            ft.SafeArea(
                ft.Text(f"Configuración incompleta: {e}. Revisa el archivo .env.", color=theme.TEXTO)
            )
        )
        return

    router = Router(
        page,
        AuthService(),
        EmqxAdminService(),
        CajonesService(),
        MqttService(),
        timeout_nodo_segundos=settings.nodo_timeout_segundos,
    )
    await router.iniciar()


def run() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    ft.run(main, assets_dir=str(ASSETS_DIR))


if __name__ == "__main__":
    run()
