import asyncio
from collections.abc import Awaitable, Callable

# Callback de navegación inyectado por el router (sync o async).
Navegar = Callable[[], Awaitable[None] | None]


async def llamar(callback: Navegar) -> None: # async await para no detener la aplicación en el proceso de respuesta de una API
    resultado = callback()
    if asyncio.iscoroutine(resultado):
        await resultado
