"""Avisa cuando cambia el estado de los cajones que llega por MQTT.

"Mi reserva" y la lista del administrador consultan Supabase cada 30 s; con
esto, además, consultan en cuanto MQTT reporta un cambio (reserva creada,
cancelada o expirada, llegada o salida confirmada, vehículo que llega o sale).
También cuenta un mensaje del backend que repite el estado del cajón. Así se
hacen menos consultas (y se escriben menos logs) sin que la pantalla tarde en
enterarse.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from parking_app.viewmodels.ocupacion_viewmodel import OcupacionViewModel

logger = logging.getLogger(__name__)


class AvisoDeCambios:
    def __init__(
        self,
        ocupacion: OcupacionViewModel,
        al_cambiar: Callable[[], Awaitable[None]],
        etiqueta: Callable[[], str | None] | None = None,
    ) -> None:
        """`etiqueta`: solo vigila ese cajón (p. ej. el de la reserva); sin ella, todos."""
        self._ocupacion = ocupacion
        self._al_cambiar = al_cambiar
        self._etiqueta = etiqueta
        self._ultima: tuple | None = None
        self._escuchando = False
        self._tareas: set[asyncio.Task[None]] = set()

    def escuchar(self) -> None:
        if not self._escuchando:
            self._ultima = self._firma()
            self._ocupacion.add_listener(self._revisar)
            self._escuchando = True

    def dejar(self) -> None:
        if self._escuchando:
            self._ocupacion.remove_listener(self._revisar)
            self._escuchando = False

    def _firma(self) -> tuple:
        # Estado efectivo + mensajes del backend: confirmar la salida con el vehículo
        # aún en el cajón no cambia el estado, pero el backend sí publica.
        etiqueta = self._etiqueta() if self._etiqueta else None
        return tuple((c.etiqueta, c.estado, self._ocupacion.avisos_del_sistema(c.etiqueta))
                     for c in self._ocupacion.cajones
                     if etiqueta is None or c.etiqueta == etiqueta)

    def _revisar(self) -> None:
        # OcupacionViewModel también notifica cada segundo (reloj): solo cuenta un cambio real.
        firma = self._firma()
        if firma == self._ultima:
            return
        self._ultima = firma
        try:
            tarea = asyncio.get_running_loop().create_task(self._al_cambiar())
        except RuntimeError:
            logger.debug("Sin event loop: el cambio se verá en la próxima consulta")
            return
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)
