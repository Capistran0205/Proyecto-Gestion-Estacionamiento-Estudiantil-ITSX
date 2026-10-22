// Envío de notificaciones push con FCM HTTP v1.

import type { Notificacion } from "./tipos.ts";

/** "token_invalido": el dispositivo ya no existe (app desinstalada, token rotado); se borra. */
export type ResultadoPush = "enviado" | "token_invalido";

export async function enviarPush(
  proyecto: string,
  accessToken: string,
  token: string,
  notificacion: Notificacion,
  fetchFn: typeof fetch = fetch,
): Promise<ResultadoPush> {
  const respuesta = await fetchFn(
    `https://fcm.googleapis.com/v1/projects/${proyecto}/messages:send`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        message: {
          token,
          notification: { title: notificacion.titulo, body: notificacion.cuerpo },
          data: notificacion.datos,
          android: { priority: "HIGH" },
        },
      }),
      signal: AbortSignal.timeout(5000),
    },
  );
  const texto = await respuesta.text();
  if (respuesta.ok) return "enviado";
  if (esTokenInvalido(respuesta.status, texto)) return "token_invalido";
  throw new Error(`FCM: HTTP ${respuesta.status} ${texto.slice(0, 200)}`);
}

function esTokenInvalido(status: number, texto: string): boolean {
  if (status === 404) return true; // UNREGISTERED
  return status === 400 && texto.includes("registration token");
}
