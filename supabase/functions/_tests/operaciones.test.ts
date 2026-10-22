import { assertEquals, assertExists, assertStringIncludes } from "jsr:@std/assert@1";
import { ErrorRpc, MENSAJE_ERROR_INTERNO } from "../_shared/errores.ts";
import {
  barrido,
  bloquearCajon,
  confirmarLlegada,
  crearReserva,
  extenderReserva,
  ingestaSensor,
  liberarBloqueo,
  reglasReserva,
} from "../_shared/operaciones.ts";
import { cajon, CRON, DepsFalsas, sinLogs, solicitud, TOPICO_BASE, WEBHOOK } from "./dobles.ts";

const ID_RESERVA = "5b1f6c1e-2c1d-4c39-9a51-6f0e8f2a3b4c";

// --- Autenticación ---

Deno.test("sin token no se llama la rpc", async () => {
  const deps = new DepsFalsas();
  const r = await bloquearCajon(solicitud({ id_cajon: 1 }), deps);
  assertEquals(r.status, 401);
  assertEquals((await r.json()).error.codigo, "NO_AUTENTICADO");
  assertEquals(deps.llamadasRpc.length, 0);
});

Deno.test("token no válido responde 401", async () => {
  const deps = new DepsFalsas();
  const r = await bloquearCajon(solicitud({ id_cajon: 1 }, { token: "falso" }), deps);
  assertEquals(r.status, 401);
  assertEquals(deps.llamadasRpc.length, 0);
});

Deno.test("solo acepta POST", async () => {
  const r = await bloquearCajon(solicitud(null, { metodo: "GET", token: "token-ana" }), new DepsFalsas());
  assertEquals(r.status, 405);
});

Deno.test("el id del usuario sale del JWT, nunca del cuerpo", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push({ cajon: cajon(2), cajones_liberados: [] });
  await bloquearCajon(solicitud({ id_cajon: 2, id_usuario: "uid-otro", p_id_usuario: "uid-otro" }, {
    token: "token-ana",
  }), deps);
  assertEquals(deps.llamadasRpc, [{ nombre: "bloquear_cajon", args: { p_id_usuario: "uid-ana", p_id_cajon: 2 } }]);
});

Deno.test("cuerpo inválido responde 400 sin llamar la rpc", async () => {
  const deps = new DepsFalsas();
  const r = await bloquearCajon(solicitud({ id_cajon: "2" }, { token: "token-ana" }), deps);
  assertEquals(r.status, 400);
  assertEquals((await r.json()).error.codigo, "SOLICITUD_INVALIDA");
  assertEquals(deps.llamadasRpc.length, 0);
});

// --- Mapeo de errores (HINT → respuesta) ---

Deno.test("un error de negocio devuelve su código y el mensaje de la función SQL", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(
    new ErrorRpc("Otro estudiante está reservando este cajón en este momento.", "P0001", "CAJON_BLOQUEADO"),
  );
  const r = await sinLogs(() => bloquearCajon(solicitud({ id_cajon: 1 }, { token: "token-ana" }), deps));
  assertEquals(r.status, 409);
  assertEquals(await r.json(), {
    error: { codigo: "CAJON_BLOQUEADO", mensaje: "Otro estudiante está reservando este cajón en este momento." },
  });
  assertEquals(deps.publicaciones.length, 0);
});

Deno.test("los errores de horario son 422", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(new ErrorRpc("La duración máxima de una reserva es de 15 horas.", "P0001", "DURACION_EXCEDIDA"));
  const r = await sinLogs(() =>
    crearReserva(solicitud({
      id_cajon: 1,
      fecha_inicio: "2026-10-06T11:00:00-06:00",
      fecha_fin: "2026-10-06T23:00:00-06:00",
    }, { token: "token-ana" }), deps)
  );
  assertEquals(r.status, 422);
  assertEquals((await r.json()).error.codigo, "DURACION_EXCEDIDA");
});

Deno.test("un error inesperado no expone detalles internos", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(new ErrorRpc('relation "reservas" does not exist', "42P01"));
  const r = await sinLogs(() => bloquearCajon(solicitud({ id_cajon: 1 }, { token: "token-ana" }), deps));
  assertEquals(r.status, 500);
  assertEquals(await r.json(), { error: { codigo: "ERROR_INTERNO", mensaje: MENSAJE_ERROR_INTERNO } });
});

Deno.test("ante deadlock se reintenta la rpc una vez", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(new ErrorRpc("deadlock detected", "40P01"), { cajon: cajon(1), cajones_liberados: [] });
  const r = await sinLogs(() => bloquearCajon(solicitud({ id_cajon: 1 }, { token: "token-ana" }), deps));
  assertEquals(r.status, 200);
  assertEquals(deps.llamadasRpc.length, 2);
});

Deno.test("un segundo deadlock ya no se reintenta", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(new ErrorRpc("deadlock", "40P01"), new ErrorRpc("deadlock", "40P01"));
  const r = await sinLogs(() => bloquearCajon(solicitud({ id_cajon: 1 }, { token: "token-ana" }), deps));
  assertEquals(r.status, 500);
  assertEquals(deps.llamadasRpc.length, 2);
});

// --- Publicación MQTT y eventos tras cada rpc ---

Deno.test("bloquear publica cada cajón devuelto y registra solo los que cambiaron", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push({
    cajon: cajon(2, { sistema: "bloqueado" }),
    cajones_liberados: [cajon(1, { sistema: "liberado", nuevo: "libre" }), cajon(3, { cambio: false, sistema: "liberado" })],
    fecha_inicio: "2026-10-06T17:00:00+00:00",
  });
  const r = await bloquearCajon(solicitud({ id_cajon: 2 }, { token: "token-ana" }), deps);
  assertEquals(r.status, 200);
  assertEquals((await r.json()).fecha_inicio, "2026-10-06T17:00:00+00:00");
  assertEquals(deps.publicaciones, [
    { topico: `${TOPICO_BASE}/1`, payload: { id_modulo: 1, estado: "liberado" } },
    { topico: `${TOPICO_BASE}/3`, payload: { id_modulo: 3, estado: "liberado" } },
    { topico: `${TOPICO_BASE}/2`, payload: { id_modulo: 2, estado: "bloqueado" } },
  ]);
  assertEquals(deps.eventos.map((e) => e.etiqueta), ["C1", "C2"]);
  assertEquals(deps.eventos[0].origen_evento, "sistema");
});

Deno.test("bloquear incluye el tiempo de llegada y la tolerancia de config_sistema", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push({ cajon: cajon(1), cajones_liberados: [] });
  const r = await bloquearCajon(solicitud({ id_cajon: 1 }, { token: "token-ana" }), deps);
  assertEquals((await r.json()).reglas, { cronometro_llegada_min: 60, tolerancia_min: 20 });
});

Deno.test("si no se pueden leer las reglas, el bloqueo responde igual", async () => {
  const deps = new DepsFalsas();
  deps.fallaConfig = true;
  deps.respuestas.push({ cajon: cajon(1), cajones_liberados: [], fecha_inicio: "x" });
  const r = await sinLogs(() => bloquearCajon(solicitud({ id_cajon: 1 }, { token: "token-ana" }), deps));
  assertEquals(r.status, 200);
  const cuerpo = await r.json();
  assertEquals(cuerpo.fecha_inicio, "x");
  assertEquals(cuerpo.reglas, undefined);
});

Deno.test("reglas-reserva devuelve los tiempos de config_sistema a un usuario con sesión", async () => {
  const deps = new DepsFalsas();
  const r = await reglasReserva(solicitud({}, { token: "token-ana" }), deps);
  assertEquals(r.status, 200);
  assertEquals(await r.json(), {
    cronometro_llegada_min: 60,
    tolerancia_min: 20,
    aviso_fin_min: 10,
    duracion_max_h: 15,
  });
  assertEquals(deps.llamadasRpc.length, 0);
});

Deno.test("reglas-reserva exige sesión", async () => {
  const r = await reglasReserva(solicitud({}), new DepsFalsas());
  assertEquals(r.status, 401);
});

Deno.test("el tópico usa el número de módulo de la etiqueta, no el id del cajón", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push({ cajon: cajon(17, { etiqueta: "C4" }), cajones_liberados: [] });
  await bloquearCajon(solicitud({ id_cajon: 17 }, { token: "token-ana" }), deps);
  assertEquals(deps.publicaciones[0], {
    topico: `${TOPICO_BASE}/4`,
    payload: { id_modulo: 4, estado: "bloqueado" },
  });
});

Deno.test("crear reserva registra el evento con el esquema de la guía de Firestore", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push({ id_reserva: ID_RESERVA, codigo_qr: "abc", cajon: cajon(1, { sistema: "reservado", nuevo: "reservado" }) });
  await crearReserva(solicitud({
    id_cajon: 1,
    fecha_inicio: "2026-10-06T11:00:00-06:00",
    fecha_fin: "2026-10-06T14:00:00-06:00",
  }, { token: "token-ana" }), deps);
  assertEquals(deps.llamadasRpc[0].args, {
    p_id_usuario: "uid-ana",
    p_id_cajon: 1,
    p_fecha_inicio: "2026-10-06T11:00:00-06:00",
    p_fecha_fin: "2026-10-06T14:00:00-06:00",
  });
  const { marca_tiempo, ...evento } = deps.eventos[0];
  assertEquals(evento, { id_cajon: 1, etiqueta: "C1", estado_nuevo: "reservado", origen_evento: "sistema" });
  assertEquals(marca_tiempo instanceof Date, true);
  assertEquals(deps.publicaciones[0].payload.estado, "reservado");
});

Deno.test("liberar sin id_cajon libera todos los bloqueos del estudiante", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push({ cajones: [cajon(2, { sistema: "liberado", nuevo: "libre" })] });
  const r = await liberarBloqueo(solicitud({}, { token: "token-ana" }), deps);
  assertEquals(r.status, 200);
  assertEquals(deps.llamadasRpc[0].args, { p_id_usuario: "uid-ana", p_id_cajon: null });
  assertEquals(deps.publicaciones[0].payload, { id_modulo: 2, estado: "liberado" });
});

Deno.test("extender no publica nada (el cajón no cambia)", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push({ id_reserva: ID_RESERVA, id_cajon: 1, fecha_fin: "2026-10-06T21:00:00+00:00" });
  const r = await extenderReserva(solicitud({ id_reserva: ID_RESERVA }, { token: "token-ana" }), deps);
  assertEquals(r.status, 200);
  assertEquals(deps.publicaciones.length + deps.eventos.length, 0);
});

Deno.test("si un efecto falla se reintenta una vez y la respuesta no cambia", async () => {
  const deps = new DepsFalsas();
  deps.fallasPublicar = 1;
  deps.fallasEvento = 2; // falla también el reintento
  deps.respuestas.push({ cajon: cajon(1), cajones_liberados: [] });
  const r = await sinLogs(() => bloquearCajon(solicitud({ id_cajon: 1 }, { token: "token-ana" }), deps));
  assertEquals(r.status, 200);
  assertEquals(deps.publicaciones.length, 1); // el reintento sí pasó
  assertEquals(deps.eventos.length, 0);
});

// --- Confirmación de llegada (administrador) ---

Deno.test("un estudiante no puede confirmar llegadas", async () => {
  const deps = new DepsFalsas();
  const r = await confirmarLlegada(solicitud({ codigo_qr: "abc" }, { token: "token-ana" }), deps);
  assertEquals(r.status, 403);
  assertEquals(deps.llamadasRpc.length, 0);
});

Deno.test("el administrador confirma con su id del JWT y el evento tiene origen administrador", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push({ id_reserva: ID_RESERVA, cajon: cajon(1, { cambio: true, sistema: "reservado" }) });
  const r = await confirmarLlegada(solicitud({ codigo_qr: "  abc123  " }, { token: "token-admin" }), deps);
  assertEquals(r.status, 200);
  assertEquals(deps.llamadasRpc[0].args, { p_id_admin: "uid-admin", p_codigo_qr: "abc123" });
  assertEquals(deps.eventos[0].origen_evento, "administrador");
});

Deno.test("QR expirado se reporta con su motivo (RF-11)", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(new ErrorRpc("El código QR expiró: se agotó el tiempo de llegada.", "P0001", "QR_EXPIRADO"));
  const r = await sinLogs(() => confirmarLlegada(solicitud({ codigo_qr: "abc" }, { token: "token-admin" }), deps));
  assertEquals(r.status, 409);
  assertEquals((await r.json()).error.mensaje, "El código QR expiró: se agotó el tiempo de llegada.");
});

// --- ingesta-sensor ---

function lectura(cuerpo: unknown, secreto = WEBHOOK) {
  return solicitud(cuerpo, { headers: { "x-webhook-secret": secreto } });
}

function resultadoIngesta(extra: Record<string, unknown> = {}) {
  return {
    cajon: cajon(3, { cambio: false, sistema: "liberado", nuevo: "libre" }),
    estado_sensor_anterior: "ocupado",
    cambio_sensor: false,
    reserva_finalizada: null,
    conflicto: null,
    ...extra,
  };
}

Deno.test("ingesta sin el secreto correcto responde 401", async () => {
  const deps = new DepsFalsas();
  const r = await ingestaSensor(lectura({ id_modulo: 1, estado: "libre" }, "otro"), deps);
  assertEquals(r.status, 401);
  assertEquals(deps.llamadasRpc.length, 0);
});

Deno.test("ingesta traduce id_modulo al id del cajón por su etiqueta", async () => {
  const deps = new DepsFalsas();
  deps.catalogo = [{ id_cajon: 30, etiqueta: "C3" }];
  deps.respuestas.push(resultadoIngesta());
  await ingestaSensor(lectura({ id_modulo: 3, estado: "no conectado" }), deps);
  assertEquals(deps.llamadasRpc[0].args, { p_id_cajon: 30, p_estado: "no conectado" });
});

// Formato de la regla: SELECT payload, timestamp FROM "infraestructura/pruebaiot/prueba1"
const TIMESTAMP_EMQX = Date.parse("2026-10-06T17:20:05.123Z");

Deno.test("ingesta acepta el mensaje de la regla de EMQX (payload como texto + timestamp)", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(resultadoIngesta({ cambio_sensor: true }));
  const r = await ingestaSensor(
    lectura({ payload: '{"id_modulo": 3, "estado": "libre"}', timestamp: TIMESTAMP_EMQX }),
    deps,
  );
  assertEquals(r.status, 200);
  assertEquals(deps.llamadasRpc[0].args.p_estado, "libre");
  // La marca de tiempo es la del mensaje en el broker, no la de la función.
  assertEquals(deps.eventos[0].marca_tiempo, new Date(TIMESTAMP_EMQX));
});

Deno.test("ingesta de un módulo inexistente responde 404", async () => {
  const deps = new DepsFalsas();
  const r = await ingestaSensor(lectura({ id_modulo: 9, estado: "libre" }), deps);
  assertEquals(r.status, 404);
  assertEquals(deps.llamadasRpc.length, 0);
});

Deno.test("una lectura repetida publica pero no registra evento", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(resultadoIngesta());
  await ingestaSensor(lectura({ id_modulo: 3, estado: "libre" }), deps);
  assertEquals(deps.publicaciones.length, 1);
  assertEquals(deps.eventos.length, 0);
});

Deno.test("si cambia el sensor se registra el evento aunque el estado efectivo no cambie", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(resultadoIngesta({ cambio_sensor: true }));
  await ingestaSensor(lectura({ id_modulo: 3, estado: "libre" }), deps);
  assertEquals(deps.eventos.length, 1);
  assertEquals(deps.eventos[0].origen_evento, "sensor");
});

Deno.test("RF-14: al salir el vehículo de una reserva en uso se registra el cajón libre", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(resultadoIngesta({
    cajon: cajon(3, { nuevo: "libre", sistema: "liberado" }),
    cambio_sensor: true,
    reserva_finalizada: { id_reserva: ID_RESERVA, id_usuario: "uid-ana" },
  }));
  const r = await sinLogs(() => ingestaSensor(lectura({ id_modulo: 3, estado: "libre" }), deps));
  assertEquals((await r.json()).reserva_finalizada.id_reserva, ID_RESERVA);
  assertEquals(deps.eventos[0].estado_nuevo, "libre");
  assertEquals(deps.publicaciones[0].payload, { id_modulo: 3, estado: "liberado" });
});

Deno.test("un vehículo en un cajón reservado avisa a los administradores", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push(resultadoIngesta({
    cajon: cajon(3, { nuevo: "ocupado", sistema: "reservado" }),
    cambio_sensor: true,
    conflicto: "reservado",
  }));
  await sinLogs(() => ingestaSensor(lectura({ id_modulo: 3, estado: "ocupado" }), deps));
  assertEquals(deps.notificaciones.length, 1);
  assertEquals(deps.notificaciones[0].destino, { rol: "administrador" });
  assertEquals(deps.notificaciones[0].notificacion.datos.tipo, "conflicto_sensor");
  assertEquals(deps.eventos[0].estado_nuevo, "ocupado");
  // La lectura física manda, pero el retain sigue diciendo "reservado".
  assertEquals(deps.publicaciones[0].payload.estado, "reservado");
});

// --- barrido ---

function cron(secreto = CRON) {
  return solicitud({}, { headers: { "x-cron-secret": secreto } });
}

Deno.test("barrido sin el secreto correcto responde 401", async () => {
  const deps = new DepsFalsas();
  const r = await barrido(cron("otro"), deps);
  assertEquals(r.status, 401);
  assertEquals(deps.llamadasRpc.length, 0);
});

Deno.test("barrido publica, registra y notifica cada tipo con id_reserva", async () => {
  const deps = new DepsFalsas();
  const aviso = (id: string, extra = {}) => ({ id_reserva: id, id_usuario: "uid-ana", id_cajon: 2, ...extra });
  deps.respuestas.push({
    cajones: [cajon(2, { sistema: "liberado", nuevo: "libre" })],
    retrasos: [aviso("r1", { tolerancia_hasta: "2026-10-06T17:20:00+00:00" })],
    expiradas: [aviso("r2")],
    fin_proximo: [aviso("r3", { fecha_fin: "2026-10-06T20:00:00+00:00" })],
    fin_alcanzado: [aviso("r4", { fecha_fin: "2026-10-06T20:00:00+00:00" })],
  });
  const r = await barrido(cron(), deps);
  assertEquals(await r.json(), { cajones: 1, retrasos: 1, expiradas: 1, fin_proximo: 1, fin_alcanzado: 1 });
  assertEquals(deps.publicaciones[0].payload, { id_modulo: 2, estado: "liberado" });
  assertEquals(deps.eventos[0].origen_evento, "sistema"); // el cajón se liberó por la expiración

  const porTipo = Object.fromEntries(deps.notificaciones.map((n) => [n.notificacion.datos.tipo, n]));
  assertEquals(Object.keys(porTipo).sort(), ["fin_alcanzado", "fin_proximo", "reserva_expirada", "retraso_llegada"]);
  for (const n of deps.notificaciones) {
    assertEquals(n.destino, { idUsuario: "uid-ana" });
    assertExists(n.notificacion.datos.id_reserva);
  }
  // Horas en la zona del instituto (UTC-6).
  assertStringIncludes(porTipo.retraso_llegada.notificacion.cuerpo, "11:20");
  assertStringIncludes(porTipo.retraso_llegada.notificacion.cuerpo, "C2");
  assertStringIncludes(porTipo.fin_proximo.notificacion.cuerpo, "14:00");
  assertEquals(porTipo.fin_proximo.notificacion.datos.accion, "extender");
});

Deno.test("barrido sin trabajo no notifica", async () => {
  const deps = new DepsFalsas();
  deps.respuestas.push({ cajones: [], retrasos: [], expiradas: [], fin_proximo: [], fin_alcanzado: [] });
  const r = await barrido(cron(), deps);
  assertEquals(r.status, 200);
  assertEquals(deps.notificaciones.length + deps.publicaciones.length, 0);
});
