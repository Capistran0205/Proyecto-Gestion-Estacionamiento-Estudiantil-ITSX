// Notificaciones push y eventos de Firestore: qué se borra y cuándo se registra.

import { assertEquals } from "jsr:@std/assert@1";
import { propagarCajones } from "../_shared/efectos.ts";
import { enviarAlDispositivo } from "../_shared/fcm.ts";
import type { Notificacion } from "../_shared/tipos.ts";
import { cajon, DepsFalsas, sinLogs } from "./dobles.ts";

const NOTIFICACION: Notificacion = {
  titulo: "t",
  cuerpo: "c",
  datos: { tipo: "fin_proximo", id_reserva: "r1" },
};

/** Anota los tokens que se borrarían de dispositivos_fcm. */
function borradorFalso() {
  const borrados: string[] = [];
  return {
    borrados,
    borrar: (token: string) => {
      borrados.push(token);
      return Promise.resolve();
    },
  };
}

Deno.test("push: un token inválido se borra de dispositivos_fcm", async () => {
  const { borrar, borrados } = borradorFalso();
  let envios = 0;

  await sinLogs(() =>
    enviarAlDispositivo(borrar, "p", "tok", "viejo", NOTIFICACION, () => {
      envios++;
      return Promise.resolve("token_invalido" as const);
    })
  );

  assertEquals(envios, 1);
  assertEquals(borrados, ["viejo"]);
});

Deno.test("push: un envío correcto no borra el token", async () => {
  const { borrar, borrados } = borradorFalso();

  await enviarAlDispositivo(borrar, "p", "tok", "vivo", NOTIFICACION, () => Promise.resolve("enviado" as const));

  assertEquals(borrados, []);
});

Deno.test("push: un fallo transitorio se reintenta una vez y no borra el token", async () => {
  const { borrar, borrados } = borradorFalso();
  let envios = 0;

  await sinLogs(() =>
    enviarAlDispositivo(borrar, "p", "tok", "vivo", NOTIFICACION, () => {
      envios++;
      return envios === 1 ? Promise.reject(new Error("FCM: HTTP 503")) : Promise.resolve("enviado" as const);
    })
  );

  assertEquals(envios, 2);
  assertEquals(borrados, []);
});

Deno.test("push: si el reintento también falla, no lanza ni borra el token", async () => {
  const { borrar, borrados } = borradorFalso();
  let envios = 0;

  await sinLogs(() =>
    enviarAlDispositivo(borrar, "p", "tok", "vivo", NOTIFICACION, () => {
      envios++;
      return Promise.reject(new Error("FCM: HTTP 503"));
    })
  );

  assertEquals(envios, 2);
  assertEquals(borrados, []);
});

Deno.test("Firestore: solo se registra el evento de los cajones que cambiaron", async () => {
  const deps = new DepsFalsas();

  await propagarCajones(deps, [cajon(1, { cambio: true }), cajon(2, { cambio: false })], {
    origen: "sistema",
  });

  // El retain de MQTT se publica siempre; el evento de Firestore, solo con cambio.
  assertEquals(deps.publicaciones.length, 2);
  assertEquals(deps.eventos.map((e) => e.id_cajon), [1]);
});

Deno.test("Firestore: un cambio de lectura del sensor registra el evento aunque el estado no cambie", async () => {
  const deps = new DepsFalsas();

  await propagarCajones(deps, [cajon(3, { cambio: false })], { origen: "sensor", cambioSensor: true });

  assertEquals(deps.eventos.map((e) => e.id_cajon), [3]);
});

Deno.test("Firestore: sin cambio ni cambio de sensor no se registra nada", async () => {
  const deps = new DepsFalsas();

  await propagarCajones(deps, [cajon(4, { cambio: false })], { origen: "sensor", cambioSensor: false });

  assertEquals(deps.eventos, []);
});
