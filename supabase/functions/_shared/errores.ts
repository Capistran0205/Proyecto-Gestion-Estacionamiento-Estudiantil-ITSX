// Traducción de errores a la respuesta para la app: { error: { codigo, mensaje } }.
// Los errores de negocio vienen de las funciones SQL con un código en HINT y un
// mensaje ya redactado para el estudiante; aquí solo se elige el status HTTP.

import { ErrorHttp, json } from "./http.ts";

/** Error de una llamada rpc (PostgREST). */
export class ErrorRpc extends Error {
  constructor(
    mensaje: string,
    /** SQLSTATE, p. ej. "P0001" (raise exception) o "40P01" (deadlock). */
    readonly codigo?: string,
    readonly hint?: string,
  ) {
    super(mensaje);
  }
}

export const SQLSTATE_DEADLOCK = "40P01";

export const MENSAJE_ERROR_INTERNO =
  "No fue posible completar la operación. Intenta de nuevo en un momento.";

/** HINT de las funciones SQL → status HTTP. */
export const ERRORES_NEGOCIO: Readonly<Record<string, number>> = {
  // Cuenta y permisos
  CUENTA_INACTIVA: 403,
  NO_AUTORIZADO: 403,
  NO_AUTENTICADO: 401,
  // Cajón
  CAJON_NO_EXISTE: 404,
  CAJON_INACTIVO: 409,
  CAJON_NO_CONECTADO: 409,
  CAJON_OCUPADO: 409,
  CAJON_RESERVADO: 409,
  CAJON_BLOQUEADO: 409,
  CAJON_NO_DISPONIBLE: 409,
  BLOQUEO_EXPIRADO: 409,
  // Reserva
  RESERVA_ACTIVA: 409,
  RESERVA_NO_ENCONTRADA: 404,
  ESTADO_INVALIDO: 409,
  INICIO_CAMBIO: 409,
  EXTENSION_NO_PERMITIDA: 422,
  // Ventana de horario (RF-01, RF-04)
  FUERA_DE_HORARIO: 422,
  FIN_INVALIDO: 422,
  OTRO_DIA: 422,
  DURACION_EXCEDIDA: 422,
  // QR (RF-11)
  QR_INVALIDO: 404,
  QR_CANCELADO: 409,
  QR_EXPIRADO: 409,
  QR_USADO: 409,
  // Ingesta y FCM
  ESTADO_SENSOR_INVALIDO: 400,
  TOKEN_INVALIDO: 400,
};

export function respuestaDeError(e: unknown): Response {
  if (e instanceof ErrorHttp) {
    return json({ error: { codigo: e.codigo, mensaje: e.message } }, e.status);
  }
  if (e instanceof ErrorRpc && e.hint && e.hint in ERRORES_NEGOCIO) {
    console.info(`Regla de negocio: ${e.hint} — ${e.message}`);
    return json({ error: { codigo: e.hint, mensaje: e.message } }, ERRORES_NEGOCIO[e.hint]);
  }
  console.error("Error inesperado:", e);
  return json({ error: { codigo: "ERROR_INTERNO", mensaje: MENSAJE_ERROR_INTERNO } }, 500);
}
