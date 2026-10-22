// Escritura de eventos de ocupación en Firestore (API REST v1).

export const COLECCION_EVENTOS = "eventos_ocupacion";

type ValorFirestore = Record<string, unknown>;

export function valorFirestore(valor: unknown): ValorFirestore {
  if (valor === null || valor === undefined) return { nullValue: null };
  if (valor instanceof Date) return { timestampValue: valor.toISOString() };
  if (typeof valor === "boolean") return { booleanValue: valor };
  if (typeof valor === "number") {
    return Number.isInteger(valor) ? { integerValue: String(valor) } : { doubleValue: valor };
  }
  if (typeof valor === "string") return { stringValue: valor };
  if (Array.isArray(valor)) return { arrayValue: { values: valor.map(valorFirestore) } };
  if (typeof valor === "object") {
    return { mapValue: { fields: camposFirestore(valor as Record<string, unknown>) } };
  }
  return { stringValue: String(valor) };
}

export function camposFirestore(datos: Record<string, unknown>): Record<string, ValorFirestore> {
  return Object.fromEntries(
    Object.entries(datos)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, valorFirestore(v)]),
  );
}

export async function crearDocumento(
  proyecto: string,
  accessToken: string,
  coleccion: string,
  datos: Record<string, unknown>,
  fetchFn: typeof fetch = fetch,
): Promise<void> {
  const url = `https://firestore.googleapis.com/v1/projects/${proyecto}/databases/(default)/documents/${coleccion}`;
  const respuesta = await fetchFn(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ fields: camposFirestore(datos) }),
    signal: AbortSignal.timeout(5000),
  });
  const texto = await respuesta.text();
  if (!respuesta.ok) {
    throw new Error(`Firestore: HTTP ${respuesta.status} ${texto.slice(0, 200)}`);
  }
}
