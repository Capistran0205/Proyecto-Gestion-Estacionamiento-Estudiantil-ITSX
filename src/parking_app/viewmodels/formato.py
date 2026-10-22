"""Formatos de hora compartidos por los ViewModels de reservas."""

from datetime import datetime, timedelta

from parking_app.core.config import ZONA_HORARIA


def hora_local(fecha: datetime) -> str:
    """"14:00" en la hora del instituto."""
    return fecha.astimezone(ZONA_HORARIA).strftime("%H:%M")


def cuenta_regresiva(restante: timedelta) -> str:
    """mm:ss hasta 60:00; después h:mm:ss. Nunca negativa."""
    segundos = max(0, int(restante.total_seconds()))
    horas, resto = divmod(segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    if horas and (horas, minutos, segundos) != (1, 0, 0):
        return f"{horas}:{minutos:02}:{segundos:02}"
    # Hasta 60:00 se muestra como mm:ss (la hora para llegar completa).
    return f"{horas * 60 + minutos:02}:{segundos:02}"


def hh_mm_ss(restante: timedelta) -> str:
    """Siempre hh:mm:ss (tiempo de uso restante). Nunca negativa."""
    segundos = max(0, int(restante.total_seconds()))
    horas, resto = divmod(segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    return f"{horas:02}:{minutos:02}:{segundos:02}"


def horas_totales(inicio: datetime, fin: datetime) -> str:
    """"3 h" (las reservas van por horas completas; si no, con un decimal)."""
    horas = (fin - inicio).total_seconds() / 3600
    return f"{horas:.0f} h" if horas == int(horas) else f"{horas:.1f} h"


def id_corto(id_reserva: str) -> str:
    """"#5B1F6C1E": los primeros 8 caracteres del uuid, suficientes para identificarla."""
    return "#" + id_reserva.replace("-", "")[:8].upper()
