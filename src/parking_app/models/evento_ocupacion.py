import json
from dataclasses import dataclass, field
from datetime import datetime

from parking_app.core.config import NUM_CAJONES
from parking_app.models.cajon_estacionamiento import EstadoCajon, etiqueta_de_modulo

# Clase representativa para mensajes de error por una json mal formado desde el ESP32 al EMQX y al recibirlo 
# MqttService lo registra en el log y lo descarta
class PayloadInvalidoError(ValueError):
    """El mensaje MQTT no tiene el formato esperado."""

# Clase representativa la cual recibe un mensaje de MQTT desde el método from_payload(), el cual consiste en un  json, dicho json se valida
# para revisar que cuente con la siguiente estructura: {"id_modulo", "estado"} y que los valores internos válidos son para el id_modulo del 1-4
# y la etiqueta del estado debe ser "libre" o "ocupado".
@dataclass(frozen=True)
class EventoOcupacion:
    id_modulo: int
    estado: EstadoCajon
    origen_evento: str = "mqtt"
    marca_tiempo: datetime = field(default_factory=datetime.now)

    @property
    def etiqueta_cajon(self) -> str:
        return etiqueta_de_modulo(self.id_modulo)

    @classmethod
    def from_payload(cls, payload: bytes | str, origen: str = "mqtt") -> "EventoOcupacion":
        """Parsea `{"id_modulo": 1-4, "estado": "libre"|"ocupado"|...}`."""
        try:
            datos = json.loads(payload)
            id_modulo = datos["id_modulo"]
            estado = EstadoCajon.parse(datos["estado"])
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, KeyError, ValueError) as e:
            raise PayloadInvalidoError(f"Payload inválido: {payload!r}") from e

        if isinstance(id_modulo, bool) or not isinstance(id_modulo, int):
            raise PayloadInvalidoError(f"id_modulo no es entero: {id_modulo!r}")
        if not 1 <= id_modulo <= NUM_CAJONES:
            raise PayloadInvalidoError(f"id_modulo fuera de rango: {id_modulo}")

        return cls(id_modulo=id_modulo, estado=estado, origen_evento=origen)
