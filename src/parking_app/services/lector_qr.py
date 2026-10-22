"""Lectura de QR con OpenCV a partir de los cuadros de flet-camera (Módulo C).

En Android, flet-camera entrega cada cuadro ya convertido a JPEG. Aquí:
JPEG -> escala de grises -> (reducción) -> cv2.QRCodeDetector. Validado en un
teléfono real con app_escaneoqr_prueba (≈ 1.7 s con resolución media).
Es bloqueante: usar desde un hilo.
"""

import re

import cv2
import numpy as np

# Formato de reservas.codigo_qr: uuid sin guiones (32 hexadecimales).
FORMATO_CODIGO = re.compile(r"^[0-9a-f]{32}$")
LADO_MAXIMO = 720


class LectorQr:
    def __init__(self, lado_maximo: int = LADO_MAXIMO) -> None:
        self._lado_maximo = lado_maximo
        self._detector = cv2.QRCodeDetector()

    def leer(self, imagen: bytes) -> str | None:
        """Texto del QR de una imagen codificada (JPEG/PNG), o None si no hay uno legible."""
        gris = cv2.imdecode(np.frombuffer(imagen, np.uint8), cv2.IMREAD_GRAYSCALE)
        if gris is None:
            return None
        alto, ancho = gris.shape
        if max(alto, ancho) > self._lado_maximo:
            escala = self._lado_maximo / max(alto, ancho)
            gris = cv2.resize(gris, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
        try:
            texto, _puntos, _ = self._detector.detectAndDecode(gris)
        except cv2.error:
            return None
        texto = (texto or "").strip()
        return texto or None


def es_codigo_del_sistema(texto: str) -> bool:
    return bool(FORMATO_CODIGO.match(texto))
