"""Patrón observer mínimo para sincronizar View <-> ViewModel.

Flet no tiene data binding nativo: el ViewModel hereda de `Observable` y llama
`notify_listeners()` cuando cambia su estado; la View se suscribe con
`add_listener()` y vuelve a pintarse.
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

Listener = Callable[[], None]


class Observable:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def notify_listeners(self) -> None:
        # Copia: un listener puede desuscribirse mientras se notifica.
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                # Un listener roto (p. ej. una vista ya desmontada) no debe
                # impedir que el resto se entere del cambio.
                logger.exception("Error en listener de %s", type(self).__name__)
