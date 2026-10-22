"""QR de la reserva generado en el teléfono con segno (sin red, RNF-08)."""

import io
from functools import lru_cache

import segno


@lru_cache(maxsize=4)
def qr_png(codigo: str) -> bytes:
    """PNG en blanco y negro con margen (zona de silencio) para leerlo bien en la caseta."""
    buffer = io.BytesIO()
    # make_qr y no make: nunca un Micro QR, que cv2.QRCodeDetector no lee (Módulo C).
    segno.make_qr(codigo, error="m").save(buffer, kind="png", scale=10, border=2)
    return buffer.getvalue()
