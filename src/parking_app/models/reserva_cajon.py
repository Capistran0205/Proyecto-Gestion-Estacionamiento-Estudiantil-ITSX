from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


# Estados de `reservas.estado` (estado_reserva_enum en Supabase).
class EstadoReserva(StrEnum):
    PENDIENTE_LLEGADA = "pendiente_llegada"
    EN_USO = "en_uso"
    FINALIZADA = "finalizada"
    CANCELADA = "cancelada"
    EXPIRADA = "expirada"

    @property
    def vigente(self) -> bool:
        return self in (EstadoReserva.PENDIENTE_LLEGADA, EstadoReserva.EN_USO)


def _fecha(valor: Any) -> datetime | None:
    if valor is None or isinstance(valor, datetime):
        return valor
    return datetime.fromisoformat(str(valor))


# Reserva de un cajón (fila de `reservas` o respuesta de crear-reserva).
@dataclass(frozen=True)
class ReservaCajon:
    id_reserva: str
    id_cajon: int
    codigo_qr: str
    estado: EstadoReserva
    fecha_inicio: datetime
    fecha_fin: datetime
    # Límite de llegada (RF-06); None tras registrar la llegada.
    cronometro: datetime | None = None
    fecha_llegada: datetime | None = None
    etiqueta: str | None = None
    # Tolerancia tras el cronómetro (config_sistema, llega con el bloqueo). La app
    # no puede leer config_sistema: se guarda con la reserva; None si no se conoce.
    minutos_tolerancia: int | None = None
    # Cuándo la creó el estudiante (orden de la lista del administrador).
    fecha_usuario: datetime | None = None
    # El barrido ya marcó el fin próximo (RF-12): respaldo si no se conocen las reglas.
    aviso_fin_enviado: bool = False

    @property
    def etiqueta_cajon(self) -> str:
        return self.etiqueta or f"C{self.id_cajon}"

    @property
    def limite_tolerancia(self) -> datetime | None:
        """Fin de la tolerancia: después la reserva expira (RF-08)."""
        if self.cronometro is None or self.minutos_tolerancia is None:
            return None
        return self.cronometro + timedelta(minutes=self.minutos_tolerancia)

    @classmethod
    def from_dict(cls, datos: dict[str, Any]) -> "ReservaCajon":
        # Etiqueta: guardada localmente, en "cajon" (crear-reserva) o en
        # "cajones" (select con el cajón embebido).
        cajon = datos.get("cajon") or datos.get("cajones") or {}
        return cls(
            id_reserva=str(datos["id_reserva"]),
            id_cajon=int(datos["id_cajon"]),
            codigo_qr=str(datos.get("codigo_qr") or ""),  # el administrador no lo consulta
            estado=EstadoReserva(datos["estado"]),
            fecha_inicio=_fecha(datos["fecha_inicio"]),
            fecha_fin=_fecha(datos["fecha_fin"]),
            cronometro=_fecha(datos.get("cronometro")),
            fecha_llegada=_fecha(datos.get("fecha_llegada")),
            etiqueta=datos.get("etiqueta") or cajon.get("etiqueta"),
            minutos_tolerancia=_entero(datos.get("minutos_tolerancia")),
            fecha_usuario=_fecha(datos.get("fecha_usuario")),
            aviso_fin_enviado=bool(datos.get("notificado_fin_proximo")
                                   or datos.get("aviso_fin_enviado")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Formato JSON para el almacenamiento local (se lee con from_dict)."""
        return {
            k: (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in asdict(self).items()
        }


# Respuesta de bloquear-cajon: el cajón queda apartado mientras se completa la reserva.
@dataclass(frozen=True)
class BloqueoCajon:
    id_cajon: int
    etiqueta: str
    fecha_inicio: datetime
    fin_minimo: datetime
    fin_maximo: datetime
    bloqueado_hasta: datetime
    # De config_sistema (los manda el backend); None si no llegaron.
    minutos_llegada: int | None = None
    minutos_tolerancia: int | None = None

    @classmethod
    def from_dict(cls, datos: dict[str, Any]) -> "BloqueoCajon":
        cajon = datos["cajon"]
        reglas = datos.get("reglas") or {}
        return cls(
            id_cajon=int(cajon["id_cajon"]),
            etiqueta=str(cajon["etiqueta"]),
            fecha_inicio=_fecha(datos["fecha_inicio"]),
            fin_minimo=_fecha(datos["fin_minimo"]),
            fin_maximo=_fecha(datos["fin_maximo"]),
            bloqueado_hasta=_fecha(datos["bloqueado_hasta"]),
            minutos_llegada=_entero(reglas.get("cronometro_llegada_min")),
            minutos_tolerancia=_entero(reglas.get("tolerancia_min")),
        )


@dataclass(frozen=True)
class ReglasReserva:
    """config_sistema vía reglas-reserva (la app no lee esa tabla ni repite sus valores)."""

    minutos_llegada: int | None
    minutos_tolerancia: int | None
    # "Mi reserva" en uso: anticipación del aviso de fin (RF-12) y duración máxima.
    minutos_aviso_fin: int | None = None
    horas_maximas: int | None = None

    @classmethod
    def from_dict(cls, datos: dict[str, Any]) -> "ReglasReserva":
        return cls(_entero(datos.get("cronometro_llegada_min")),
                   _entero(datos.get("tolerancia_min")),
                   _entero(datos.get("aviso_fin_min")),
                   _entero(datos.get("duracion_max_h")))


# Respuesta de confirmar-llegada (RF-10): la reserva pasa a en_uso.
@dataclass(frozen=True)
class LlegadaRegistrada:
    id_reserva: str
    id_cajon: int
    etiqueta: str
    fecha_llegada: datetime
    fecha_fin: datetime
    medio_transporte: str | None
    nombre_estudiante: str

    @classmethod
    def from_dict(cls, datos: dict[str, Any]) -> "LlegadaRegistrada":
        cajon = datos.get("cajon") or {}
        estudiante = datos.get("estudiante") or {}
        nombre = " ".join(
            str(estudiante[c]) for c in ("nombre", "apellido_paterno", "apellido_materno")
            if estudiante.get(c)
        )
        return cls(
            id_reserva=str(datos["id_reserva"]),
            id_cajon=int(datos["id_cajon"]),
            etiqueta=str(cajon.get("etiqueta") or f"C{datos['id_cajon']}"),
            fecha_llegada=_fecha(datos["fecha_llegada"]),
            fecha_fin=_fecha(datos["fecha_fin"]),
            medio_transporte=estudiante.get("medio_transporte"),
            nombre_estudiante=nombre,
        )


def _entero(valor: Any) -> int | None:
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None
