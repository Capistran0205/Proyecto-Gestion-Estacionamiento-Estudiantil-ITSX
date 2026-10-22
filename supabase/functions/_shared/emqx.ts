// Publicación en EMQX con la API HTTP v5 (POST /publish).

export interface ConfigEmqx {
  url: string;
  clave: string;
  secreto: string;
}

/** Acepta la URL con o sin /api/v5 (igual que emqx_admin_service.py). */
export function baseApi(url: string): string {
  const limpia = url.replace(/\/+$/, "");
  return limpia.includes("/api/v") ? limpia : `${limpia}/api/v5`;
}

/** QoS 1 + retain: al reconectarse, la ESP32 y la app reciben el último estado. */
export async function publicarRetenido(
  config: ConfigEmqx,
  topico: string,
  payload: string,
  fetchFn: typeof fetch = fetch,
): Promise<void> {
  const respuesta = await fetchFn(`${baseApi(config.url)}/publish`, {
    method: "POST",
    headers: {
      Authorization: `Basic ${btoa(`${config.clave}:${config.secreto}`)}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ topic: topico, payload, qos: 1, retain: true }),
    signal: AbortSignal.timeout(5000),
  });
  const texto = await respuesta.text();
  if (!respuesta.ok) {
    throw new Error(`EMQX rechazó la publicación en ${topico}: HTTP ${respuesta.status} ${texto.slice(0, 200)}`);
  }
}
