from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

# Clase representativa para los diferentes estado de los cajones de estacionamiento dentro del sistema,
# acepta mensaje "no conectado" del protocolo MQTT e incluso de la base de datos "no_conectado".
class EstadoCajon(StrEnum):
    LIBRE = "libre"
    OCUPADO = "ocupado"
    RESERVADO = "reservado"
    BLOQUEADO = "bloqueado"
    NO_CONECTADO = "no conectado"

    @classmethod
    def parse(cls, valor: Any) -> "EstadoCajon":
        """Acepta el formato MQTT ("no conectado") y el enum de la BD ("no_conectado")."""
        if not isinstance(valor, str):
            raise ValueError(f"Estado de cajón inválido: {valor!r}")
        return cls(valor.strip().lower().replace("_", " "))

    @property
    def valor_db(self) -> str:
        return self.value.replace(" ", "_")


# Lecturas posibles de un sensor (tópico prueba1); reservado y bloqueado los decide el sistema.
ESTADOS_SENSOR = frozenset({EstadoCajon.LIBRE, EstadoCajon.OCUPADO, EstadoCajon.NO_CONECTADO})


# Estado que publica el backend en reserva1/{id_modulo} (mensaje retenido).
class EstadoSistema(StrEnum):
    BLOQUEADO = "bloqueado"
    RESERVADO = "reservado"
    LIBERADO = "liberado"


def estado_efectivo(sensor: EstadoCajon, sistema: EstadoSistema) -> EstadoCajon:
    """Misma regla que recalcular_estado_cajon en la base de datos.

    1. sensor no conectado → no conectado
    2. sensor ocupado → ocupado (la lectura física manda, RNF-01)
    3. reservado → reservado
    4. bloqueado → bloqueado
    5. en otro caso → libre
    """
    if sensor in (EstadoCajon.NO_CONECTADO, EstadoCajon.OCUPADO):
        return sensor
    if sistema == EstadoSistema.RESERVADO:
        return EstadoCajon.RESERVADO
    if sistema == EstadoSistema.BLOQUEADO:
        return EstadoCajon.BLOQUEADO
    return EstadoCajon.LIBRE


def sensor_de_estado_efectivo(estado: EstadoCajon) -> EstadoCajon:
    """Lectura del sensor a partir del estado efectivo (exacta, por la regla de arriba)."""
    return estado if estado in ESTADOS_SENSOR else EstadoCajon.LIBRE


def sistema_de_estado_efectivo(estado: EstadoCajon) -> EstadoSistema:
    """Estado del sistema que se deduce del efectivo. Si el sensor manda (ocupado o no
    conectado) no se sabe si hay reserva: se asume liberado hasta el mensaje retenido."""
    if estado == EstadoCajon.RESERVADO:
        return EstadoSistema.RESERVADO
    if estado == EstadoCajon.BLOQUEADO:
        return EstadoSistema.BLOQUEADO
    return EstadoSistema.LIBERADO


def etiqueta_de_modulo(id_modulo: int) -> str:
    """id_modulo del ESP32 (1..4) -> etiqueta del cajón ("C1".."C4")."""
    return f"C{id_modulo}"


# Clase representativa de la entidad de la tabla cajones con sus atributos id_cajon, etiqueta, 
# estado_actual, estado_actividad y fecha_registro, con from_row() para construirla. 
@dataclass
class CajonEstacionamiento:
    """Fila de `public.cajones`."""

    id_cajon: int
    etiqueta: str
    estado_actual: EstadoCajon = EstadoCajon.NO_CONECTADO
    estado_actividad: bool = True
    fecha_registro: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "CajonEstacionamiento":
        try:
            estado = EstadoCajon.parse(row.get("estado_actual"))
        except ValueError:
            estado = EstadoCajon.NO_CONECTADO
        fecha = row.get("fecha_registro")
        return cls(
            id_cajon=row["id_cajon"],
            etiqueta=row["etiqueta"],
            estado_actual=estado,
            estado_actividad=bool(row.get("estado_actividad", True)),
            fecha_registro=datetime.fromisoformat(fecha) if fecha else None,
        )
