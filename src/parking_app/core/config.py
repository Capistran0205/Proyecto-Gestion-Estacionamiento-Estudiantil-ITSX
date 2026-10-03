"""Configuración de la app leída desde variables de entorno (.env)."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv

TOPICO_OCUPACION_DEFAULT = "infraestructura/pruebaiot/prueba1"
DOMINIOS_CORREO_PERMITIDOS = ("itsx.edu.mx", "xalapa.tecnm.mx")

# Login: bloqueo tras N intentos fallidos durante X segundos.
MAX_INTENTOS_LOGIN = 3
SEGUNDOS_BLOQUEO_LOGIN = 3 * 60

# Vigencia del código de recuperación (configurada en Supabase; aquí solo se muestra).
VIGENCIA_CODIGO_SEGUNDOS = 10 * 60

# Maqueta física: 4 cajones fijos (C1..C4).
NUM_CAJONES = 4


class ConfigError(RuntimeError):
    """Falta una variable de entorno obligatoria o tiene un valor inválido."""

# Clase representativa para los valores de configuración del protocolo MQTT involucrando el nombre del host, 
# el puerto y el tópico del broker
@dataclass(frozen=True)
class ConfigMqtt:
    host: str
    port: int
    topico_ocupacion: str

# Clase representativa para las credenciales de configuración del servidor EMQX
# desde la URL, la API key y el secreto de la API de EMQX, que se leen de la siguiente clase Setting
@dataclass(frozen=True)
class ConfigEmqx:
    api_url: str
    api_key: str
    api_secret: str

# Clase representativa asociada a todas las credenciales de configuración, desde Supabase hasta EMQX por el momento
@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str
    # MQTT y EMQX solo se exigen al usarse: su ausencia no impide el login.
    mqtt_broker_host: str | None
    mqtt_broker_port: int
    mqtt_topic_ocupacion: str
    emqx_api_url: str | None
    emqx_api_key: str | None
    emqx_api_secret: str | None
    # Segundos sin reportes de un nodo antes de marcarlo como "no conectado".
    nodo_timeout_segundos: int

    def mqtt(self) -> ConfigMqtt:
        if not self.mqtt_broker_host:
            raise ConfigError("Falta la variable de entorno MQTT_BROKER_HOST")
        return ConfigMqtt(self.mqtt_broker_host, self.mqtt_broker_port, self.mqtt_topic_ocupacion)

    def emqx(self) -> ConfigEmqx:
        faltantes = [
            nombre
            for nombre, valor in (
                ("EMQX_API_URL", self.emqx_api_url),
                ("EMQX_API_KEY", self.emqx_api_key),
                ("EMQX_API_SECRET", self.emqx_api_secret),
            )
            if not valor
        ]
        if faltantes:
            raise ConfigError("Faltan variables de entorno: " + ", ".join(faltantes))
        return ConfigEmqx(self.emqx_api_url, self.emqx_api_key, self.emqx_api_secret)


def _leer(nombre: str) -> str | None:
    return os.getenv(nombre, "").strip() or None


def _requerida(nombre: str) -> str:
    valor = _leer(nombre)
    if valor is None:
        raise ConfigError(f"Falta la variable de entorno {nombre}")
    return valor


def _entero(nombre: str, default: int) -> int:
    valor = _leer(nombre)
    if valor is None:
        return default
    try:
        return int(valor)
    except ValueError as e:
        raise ConfigError(f"{nombre} debe ser un número entero") from e


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(find_dotenv(usecwd=True))
    emqx_url = _leer("EMQX_API_URL")
    return Settings(
        supabase_url=_requerida("SUPABASE_URL"),
        supabase_anon_key=_requerida("SUPABASE_ANON_KEY"),
        mqtt_broker_host=_leer("MQTT_BROKER_HOST"),
        mqtt_broker_port=_entero("MQTT_BROKER_PORT", 1883),
        mqtt_topic_ocupacion=_leer("MQTT_TOPIC_OCUPACION") or TOPICO_OCUPACION_DEFAULT,
        emqx_api_url=emqx_url.rstrip("/") if emqx_url else None,
        emqx_api_key=_leer("EMQX_API_KEY"),
        emqx_api_secret=_leer("EMQX_API_SECRET"),
        nodo_timeout_segundos=_entero("NODO_TIMEOUT_SEGUNDOS", 60),
    )
