"""Snapshot del estado de los cajones desde la tabla `cajones` (requiere sesión)."""

import logging
from collections.abc import Callable

from supabase import Client

from parking_app.core.config import NUM_CAJONES
from parking_app.models.cajon_estacionamiento import (
    CajonEstacionamiento,
    EstadoCajon,
    etiqueta_de_modulo,
)

logger = logging.getLogger(__name__)

TABLA_CAJONES = "cajones"

# Clase para detectar fallas en las lecturas de la tabla. El ViewModel la atrapa y 
# la pantalla sigue funcionando: MQTT va llenando los cajones.
class CajonesNoDisponiblesError(Exception):
    """No se pudo leer el estado de los cajones."""

# Clase representativa para obtener los estados en tiempo real de los cajones de estacionamiento, 
# lee la tabla cajones de Supabase y siempre devuelve C1 a C4 en orden. Si falta un cajón o está dado de baja, 
# lo devuelve como "no conectado", y las filas inválidas se descartan.
class CajonesService:
    def __init__(self, cliente_factory: Callable[[], Client] | None = None) -> None:
        if cliente_factory is None:
            from parking_app.services.supabase_client import get_supabase

            cliente_factory = get_supabase
        self._cliente_factory = cliente_factory

    def obtener_estado_actual(self) -> list[CajonEstacionamiento]:
        """Devuelve siempre los cajones C1..C4 en orden (los faltantes, "no conectado")."""
        try:
            resultado = (
                self._cliente_factory()
                .table(TABLA_CAJONES)
                .select("id_cajon, etiqueta, estado_actividad, estado_actual, fecha_registro")
                .order("id_cajon")
                .execute()
            )
        except Exception as e:
            raise CajonesNoDisponiblesError(str(e)) from e

        por_etiqueta: dict[str, CajonEstacionamiento] = {}
        for fila in resultado.data or []:
            try:
                cajon = CajonEstacionamiento.from_row(fila)
            except (KeyError, ValueError, TypeError):
                logger.warning("Fila de cajón inválida: %r", fila)
                continue
            if not cajon.estado_actividad:
                # Cajón dado de baja: se muestra, pero sin estado confiable.
                cajon.estado_actual = EstadoCajon.NO_CONECTADO
            por_etiqueta[cajon.etiqueta] = cajon

        return [
            por_etiqueta.get(etiqueta_de_modulo(i))
            or CajonEstacionamiento(id_cajon=i, etiqueta=etiqueta_de_modulo(i))
            for i in range(1, NUM_CAJONES + 1)
        ]
