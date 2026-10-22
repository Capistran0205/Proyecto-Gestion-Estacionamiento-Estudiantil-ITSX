// Clientes HTTP de EMQX, Google OAuth, Firestore y FCM con fetch simulado.

import { assert, assertEquals, assertRejects } from "jsr:@std/assert@1";
import { baseApi, publicarRetenido } from "../_shared/emqx.ts";
import { enviarPush } from "../_shared/fcm.ts";
import { camposFirestore, crearDocumento } from "../_shared/firestore.ts";
import { cuentaDesdeBase64, proveedorDeToken } from "../_shared/google.ts";

interface Llamada {
  url: string;
  init: RequestInit;
}

function fetchFalso(respuestas: Response[]): { fetch: typeof fetch; llamadas: Llamada[] } {
  const llamadas: Llamada[] = [];
  const fn = (url: string | URL | Request, init?: RequestInit) => {
    llamadas.push({ url: String(url), init: init ?? {} });
    return Promise.resolve(respuestas.shift() ?? new Response("{}", { status: 500 }));
  };
  return { fetch: fn as typeof fetch, llamadas };
}

const NOTIFICACION = { titulo: "t", cuerpo: "c", datos: { tipo: "fin_proximo", id_reserva: "r1" } };

Deno.test("EMQX: la URL acepta o no el sufijo /api/v5", () => {
  assertEquals(baseApi("https://x.emqxsl.com:8443/"), "https://x.emqxsl.com:8443/api/v5");
  assertEquals(baseApi("https://x.emqxsl.com:8443/api/v5"), "https://x.emqxsl.com:8443/api/v5");
});

Deno.test("EMQX: publica con QoS 1, retain y autenticación básica", async () => {
  const { fetch, llamadas } = fetchFalso([new Response('{"id":"1"}')]);
  await publicarRetenido({ url: "https://broker:8443", clave: "k", secreto: "s" }, "a/b/1", '{"x":1}', fetch);
  assertEquals(llamadas[0].url, "https://broker:8443/api/v5/publish");
  assertEquals((llamadas[0].init.headers as Record<string, string>).Authorization, `Basic ${btoa("k:s")}`);
  assertEquals(JSON.parse(llamadas[0].init.body as string), {
    topic: "a/b/1",
    payload: '{"x":1}',
    qos: 1,
    retain: true,
  });
});

Deno.test("EMQX: un error HTTP se lanza para que se reintente", async () => {
  const { fetch } = fetchFalso([new Response("forbidden", { status: 403 })]);
  await assertRejects(() => publicarRetenido({ url: "https://b", clave: "k", secreto: "s" }, "t", "{}", fetch));
});

Deno.test("Firestore: codifica cada tipo de valor", () => {
  const marca = new Date("2026-10-06T17:00:00Z");
  assertEquals(camposFirestore({ a: "x", b: 3, c: true, d: null, e: marca, f: undefined }), {
    a: { stringValue: "x" },
    b: { integerValue: "3" },
    c: { booleanValue: true },
    d: { nullValue: null },
    e: { timestampValue: "2026-10-06T17:00:00.000Z" },
  });
});

Deno.test("Firestore: crea el documento en la colección con el token", async () => {
  const { fetch, llamadas } = fetchFalso([new Response("{}")]);
  await crearDocumento("proyecto", "tok", "eventos_ocupacion", { etiqueta: "C1" }, fetch);
  assertEquals(
    llamadas[0].url,
    "https://firestore.googleapis.com/v1/projects/proyecto/databases/(default)/documents/eventos_ocupacion",
  );
  assertEquals((llamadas[0].init.headers as Record<string, string>).Authorization, "Bearer tok");
});

Deno.test("FCM: envía notificación y datos", async () => {
  const { fetch, llamadas } = fetchFalso([new Response("{}")]);
  assertEquals(await enviarPush("proyecto", "tok", "dispositivo", NOTIFICACION, fetch), "enviado");
  const mensaje = JSON.parse(llamadas[0].init.body as string).message;
  assertEquals(mensaje.token, "dispositivo");
  assertEquals(mensaje.data, NOTIFICACION.datos);
  assertEquals(mensaje.notification, { title: "t", body: "c" });
});

Deno.test("FCM: un token no registrado se reporta para borrarlo", async () => {
  const { fetch } = fetchFalso([new Response('{"error":{"status":"NOT_FOUND"}}', { status: 404 })]);
  assertEquals(await enviarPush("p", "tok", "viejo", NOTIFICACION, fetch), "token_invalido");
});

Deno.test("FCM: un error del servidor se lanza para reintentar", async () => {
  const { fetch } = fetchFalso([new Response("unavailable", { status: 503 })]);
  await assertRejects(() => enviarPush("p", "tok", "d", NOTIFICACION, fetch));
});

async function cuentaDePrueba() {
  const llaves = await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true,
    ["sign", "verify"],
  );
  const pkcs8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", llaves.privateKey));
  const pem = `-----BEGIN PRIVATE KEY-----\n${btoa(String.fromCharCode(...pkcs8))}\n-----END PRIVATE KEY-----\n`;
  const json = JSON.stringify({ client_email: "sa@proyecto.iam.gserviceaccount.com", private_key: pem });
  return { cuenta: cuentaDesdeBase64(btoa(json)), publica: llaves.publicKey };
}

Deno.test("Google: firma un JWT válido y reutiliza el token hasta que vence", async () => {
  const { cuenta, publica } = await cuentaDePrueba();
  const { fetch, llamadas } = fetchFalso([
    Response.json({ access_token: "a1", expires_in: 3600 }),
    Response.json({ access_token: "a2", expires_in: 3600 }),
  ]);
  let ahora = 1_000_000_000_000;
  const token = proveedorDeToken(cuenta, undefined, fetch, () => ahora);

  assertEquals(await token(), "a1");
  assertEquals(await token(), "a1");
  assertEquals(llamadas.length, 1);

  const asercion = new URLSearchParams(llamadas[0].init.body as URLSearchParams).get("assertion")!;
  const [h, p, firma] = asercion.split(".");
  const decodificar = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
  assert(await crypto.subtle.verify("RSASSA-PKCS1-v1_5", publica, decodificar(firma), new TextEncoder().encode(`${h}.${p}`)));
  const reclamos = JSON.parse(new TextDecoder().decode(decodificar(p)));
  assertEquals(reclamos.iss, "sa@proyecto.iam.gserviceaccount.com");
  assert(reclamos.scope.includes("firebase.messaging"));

  ahora += 3600 * 1000; // vencido
  assertEquals(await token(), "a2");
});
