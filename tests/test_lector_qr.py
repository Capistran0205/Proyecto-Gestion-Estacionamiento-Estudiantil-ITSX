"""Lector de QR (OpenCV) con imágenes generadas, sin cámara."""

import io

import cv2
import numpy as np
import segno

from parking_app.services.lector_qr import LectorQr, es_codigo_del_sistema

CODIGO = "5b1f6c1e2c1d4c399a516f0e8f2a3b4c"


def _jpeg_con_qr(texto: str, lado: int = 1280) -> bytes:
    """El QR en una escena grande, como un cuadro de la cámara (se reduce a 720 px)."""
    buffer = io.BytesIO()
    segno.make_qr(texto, error="m").save(buffer, kind="png", scale=12, border=2)
    qr = cv2.imdecode(np.frombuffer(buffer.getvalue(), np.uint8), cv2.IMREAD_GRAYSCALE)
    escena = np.full((lado * 9 // 16, lado), 140, np.uint8)
    y, x = (escena.shape[0] - qr.shape[0]) // 2, (escena.shape[1] - qr.shape[1]) // 2
    escena[y:y + qr.shape[0], x:x + qr.shape[1]] = qr
    ok, jpeg = cv2.imencode(".jpg", escena, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    return jpeg.tobytes()


def test_lee_el_codigo_de_una_reserva():
    assert LectorQr().leer(_jpeg_con_qr(CODIGO)) == CODIGO


def test_sin_qr_no_lee_nada():
    ok, jpeg = cv2.imencode(".jpg", np.full((480, 720), 128, np.uint8))
    assert LectorQr().leer(jpeg.tobytes()) is None


def test_bytes_que_no_son_imagen():
    assert LectorQr().leer(b"no es una imagen") is None


def test_formato_del_sistema():
    assert es_codigo_del_sistema(CODIGO)
    assert not es_codigo_del_sistema("https://ejemplo.com")
    assert not es_codigo_del_sistema(CODIGO.upper())
