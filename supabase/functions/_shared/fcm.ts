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

/** Un reintento por dispositivo (reintentar el envío completo duplicaría avisos ya entregados). */
export async function enviarAlDispositivo(
  borrarToken: (token: string) => PromiseLike<unknown>,
  proyecto: string,
  accessToken: string,
  token: string,
  notificacion: Notificacion,
  enviar: typeof enviarPush = enviarPush,
): Promise<void> {
  for (let intento = 1; intento <= 2; intento++) {
    try {
      if ((await enviar(proyecto, accessToken, token, notificacion)) === "token_invalido") {
        console.info("Token FCM inválido; se elimina");
        await borrarToken(token);
      }
      return;
    } catch (e) {
      if (intento === 2) console.error(`No se pudo enviar la notificación ${notificacion.datos.tipo}:`, e);
    }
  }
}

function esTokenInvalido(status: number, texto: string): boolean {
  if (status === 404) return true; // UNREGISTERED
  return status === 400 && texto.includes("registration token");
}
