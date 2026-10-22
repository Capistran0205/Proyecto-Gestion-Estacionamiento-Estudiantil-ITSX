// Token OAuth 2.0 de Google a partir de la cuenta de servicio de Firebase
// (JWT firmado con RS256 y WebCrypto; sin SDK de Firebase Admin).

export interface CuentaServicio {
  client_email: string;
  private_key: string;
  token_uri?: string;
}

export const ALCANCES_FIREBASE = [
  "https://www.googleapis.com/auth/datastore",
  "https://www.googleapis.com/auth/firebase.messaging",
];

/** FIREBASE_SERVICE_ACCOUNT_B64 = JSON de la cuenta de servicio en base64. */
export function cuentaDesdeBase64(b64: string): CuentaServicio {
  const bytes = Uint8Array.from(atob(b64.trim()), (c) => c.charCodeAt(0));
  const cuenta = JSON.parse(new TextDecoder().decode(bytes));
  if (typeof cuenta?.client_email !== "string" || typeof cuenta?.private_key !== "string") {
    throw new Error("FIREBASE_SERVICE_ACCOUNT_B64 no contiene una cuenta de servicio válida");
  }
  return cuenta;
}

/** Devuelve una función que entrega un access token vigente (se reutiliza hasta 1 min antes de expirar). */
export function proveedorDeToken(
  cuenta: CuentaServicio,
  alcances: string[] = ALCANCES_FIREBASE,
  fetchFn: typeof fetch = fetch,
  ahoraMs: () => number = Date.now,
): () => Promise<string> {
  let token: string | null = null;
  let expiraMs = 0;
  return async () => {
    if (token && ahoraMs() < expiraMs - 60_000) return token;
    const uri = cuenta.token_uri ?? "https://oauth2.googleapis.com/token";
    const asercion = await firmarJwt(cuenta, alcances, uri, Math.floor(ahoraMs() / 1000));
    const respuesta = await fetchFn(uri, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
        assertion: asercion,
      }),
      signal: AbortSignal.timeout(5000),
    });
    const datos = await respuesta.json();
    if (!respuesta.ok || typeof datos.access_token !== "string") {
      throw new Error(`Google OAuth: HTTP ${respuesta.status} ${JSON.stringify(datos).slice(0, 200)}`);
    }
    token = datos.access_token as string;
    expiraMs = ahoraMs() + Number(datos.expires_in ?? 3600) * 1000;
    return token;
  };
}

async function firmarJwt(
  cuenta: CuentaServicio,
  alcances: string[],
  audiencia: string,
  ahora: number,
): Promise<string> {
  const encabezado = base64Url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const reclamos = base64Url(JSON.stringify({
    iss: cuenta.client_email,
    scope: alcances.join(" "),
    aud: audiencia,
    iat: ahora,
    exp: ahora + 3600,
  }));
  const llave = await crypto.subtle.importKey(
    "pkcs8",
    derDesdePem(cuenta.private_key),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const firma = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    llave,
    new TextEncoder().encode(`${encabezado}.${reclamos}`),
  );
  return `${encabezado}.${reclamos}.${base64Url(new Uint8Array(firma))}`;
}

function derDesdePem(pem: string): ArrayBuffer {
  const b64 = pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer;
}

function base64Url(datos: string | Uint8Array): string {
  const bytes = typeof datos === "string" ? new TextEncoder().encode(datos) : datos;
  let binario = "";
  for (const b of bytes) binario += String.fromCharCode(b);
  return btoa(binario).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
