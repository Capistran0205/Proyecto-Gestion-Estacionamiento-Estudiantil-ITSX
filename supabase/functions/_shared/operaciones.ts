// Las 9 Edge Functions. Cada index.ts solo hace servir(<operación>).
//
// Funciones de usuario: el id sale del JWT (nunca del cuerpo) y la rpc se
// ejecuta con service_role. ingesta-sensor y barrido no usan JWT
// (verify_jwt = false) y validan un secreto en un header.

import { HEADER_CRON, HEADER_WEBHOOK } from "./config.ts";
import { avisar, type ContextoEvento, moduloDeCajon, propagarCajones } from "./efectos.ts";
import { ErrorRpc, respuestaDeError, SQLSTATE_DEADLOCK } from "./errores.ts";
import {
  type Cuerpo,
  enteroPositivo,
  ErrorHttp,
  exigirSecreto,
  fecha,
  json,
  leerCuerpo,
  solicitudInvalida,
  soloPost,
  texto,
  tokenBearer,
  uuid,
} from "./http.ts";
import { notificacionConflicto, notificarBarrido, type ResultadoBarrido } from "./notificaciones.ts";
import type { CajonRecalculado, Dependencias, Manejador, OrigenEvento } from "./tipos.ts";

/** Reintenta una sola vez si Postgres abortó la transacción por deadlock. */
export async function rpcConReintento<T>(
  deps: Dependencias,
  nombre: string,
  args: Record<string, unknown>,
): Promise<T> {
  try {
    return await deps.rpc(nombre, args) as T;
  } catch (e) {
    if (e instanceof ErrorRpc && e.codigo === SQLSTATE_DEADLOCK) {
      console.warn(`Deadlock en ${nombre}; se reintenta una vez`);
      return await deps.rpc(nombre, args) as T;
    }
    throw e;
  }
}

async function autenticar(req: Request, deps: Dependencias): Promise<string> {
  const token = tokenBearer(req);
  const idUsuario = token ? await deps.idUsuarioDelToken(token) : null;
  if (!idUsuario) {
    throw new ErrorHttp(401, "NO_AUTENTICADO", "Tu sesión expiró. Inicia sesión de nuevo.");
  }
  return idUsuario;
}

// --- Funciones de usuario ---

type Resultado = Record<string, unknown>;

interface Operacion<R extends Resultado> {
  rpc: string;
  argumentos(cuerpo: Cuerpo, idUsuario: string): Record<string, unknown>;
  cajones(resultado: R): CajonRecalculado[];
  origen: OrigenEvento;
  soloAdministrador?: boolean;
  /** Datos extra para la respuesta; si fallan, la respuesta sale sin ellos. */
  complementar?(deps: Dependencias): Promise<Resultado>;
}

function operacionDeUsuario<R extends Resultado>(op: Operacion<R>): Manejador {
  return async (req, deps) => {
    try {
      soloPost(req);
      const idUsuario = await autenticar(req, deps);
      if (op.soloAdministrador && (await deps.rolDeUsuario(idUsuario)) !== "administrador") {
        throw new ErrorHttp(403, "NO_AUTORIZADO", "Solo un administrador puede validar códigos QR.");
      }
      const args = op.argumentos(await leerCuerpo(req), idUsuario);
      const resultado = await rpcConReintento<R>(deps, op.rpc, args);
      const [extra] = await Promise.all([
        op.complementar?.(deps).catch((e) => {
          console.warn(`No se pudieron agregar datos a la respuesta de ${op.rpc}:`, e);
          return {};
        }),
        propagarCajones(deps, op.cajones(resultado), { origen: op.origen }),
      ]);
      return json({ ...resultado, ...extra });
    } catch (e) {
      return respuestaDeError(e);
    }
  };
}

type ConCajon = Resultado & { cajon: CajonRecalculado };

export const bloquearCajon = operacionDeUsuario<ConCajon & { cajones_liberados: CajonRecalculado[] }>({
  rpc: "bloquear_cajon",
  argumentos: (c, id) => ({ p_id_usuario: id, p_id_cajon: enteroPositivo(c, "id_cajon") }),
  cajones: (r) => [...(r.cajones_liberados ?? []), r.cajon],
  origen: "sistema",
  // Para "Antes de confirmar": la app no lee config_sistema ni repite sus valores.
  complementar: async (deps) => ({ reglas: await leerReglas(deps) }),
});

const REGLAS_LLEGADA = ["cronometro_llegada_min", "tolerancia_min"];
// "Mi reserva" en uso: cuándo avisar del fin próximo y el límite que se muestra al extender.
const REGLAS_USO = ["aviso_fin_min", "duracion_max_h"];

/** Valores numéricos de config_sistema (la app no puede leer esa tabla). */
async function leerReglas(deps: Dependencias, claves: string[] = REGLAS_LLEGADA) {
  const cfg = await deps.configuracion(claves);
  return Object.fromEntries(claves.map((clave) => [clave, Number(cfg[clave])]));
}

/** reglas-reserva: cualquier usuario con sesión (cuentas regresivas del administrador y de "Mi reserva"). */
export const reglasReserva: Manejador = async (req, deps) => {
  try {
    soloPost(req);
    await autenticar(req, deps);
    return json(await leerReglas(deps, [...REGLAS_LLEGADA, ...REGLAS_USO]));
  } catch (e) {
    return respuestaDeError(e);
  }
};

export const liberarBloqueo = operacionDeUsuario<Resultado & { cajones: CajonRecalculado[] }>({
  rpc: "liberar_bloqueo",
  // Sin id_cajon se liberan todos los bloqueos del estudiante.
  argumentos: (c, id) => ({
    p_id_usuario: id,
    p_id_cajon: c.id_cajon === undefined || c.id_cajon === null ? null : enteroPositivo(c, "id_cajon"),
  }),
  cajones: (r) => r.cajones ?? [],
  origen: "sistema",
});

export const crearReserva = operacionDeUsuario<ConCajon>({
  rpc: "crear_reserva",
  argumentos: (c, id) => ({
    p_id_usuario: id,
    p_id_cajon: enteroPositivo(c, "id_cajon"),
    p_fecha_inicio: fecha(c, "fecha_inicio"),
    p_fecha_fin: fecha(c, "fecha_fin"),
  }),
  cajones: (r) => [r.cajon],
  origen: "sistema",
});

export const cancelarReserva = operacionDeUsuario<ConCajon>({
  rpc: "cancelar_reserva",
  argumentos: (c, id) => ({ p_id_usuario: id, p_id_reserva: uuid(c, "id_reserva") }),
  cajones: (r) => [r.cajon],
  origen: "sistema",
});

// Extender no cambia el estado del cajón: no hay nada que publicar.
export const extenderReserva = operacionDeUsuario<Resultado>({
  rpc: "extender_reserva",
  argumentos: (c, id) => ({ p_id_usuario: id, p_id_reserva: uuid(c, "id_reserva") }),
  cajones: () => [],
  origen: "sistema",
});

export const confirmarSalida = operacionDeUsuario<ConCajon>({
  rpc: "confirmar_salida",
  argumentos: (c, id) => ({ p_id_usuario: id, p_id_reserva: uuid(c, "id_reserva") }),
  cajones: (r) => [r.cajon],
  origen: "sistema",
});

export const confirmarLlegada = operacionDeUsuario<ConCajon>({
  rpc: "confirmar_llegada",
  argumentos: (c, id) => ({ p_id_admin: id, p_codigo_qr: texto(c, "codigo_qr", 128) }),
  cajones: (r) => [r.cajon],
  origen: "administrador",
  soloAdministrador: true,
});

// --- ingesta-sensor (regla de EMQX sobre prueba1) ---

interface ResultadoIngesta extends Resultado {
  cajon: CajonRecalculado;
  estado_sensor_anterior: string | null;
  cambio_sensor: boolean;
  reserva_finalizada: { id_reserva: string; id_usuario: string } | null;
  conflicto: "reservado" | "bloqueado" | null;
}

/**
 * La regla de EMQX (`SELECT payload, timestamp FROM ...`) envía
 * {"payload": "<json del ESP32>", "timestamp": <ms>}. También acepta el payload
 * como objeto o directamente {id_modulo, estado}.
 */
export function lecturaDeSensor(
  cuerpo: Cuerpo,
): { idModulo: number; estado: string; marcaTiempo?: Date } {
  const marcaTiempo = typeof cuerpo.timestamp === "number" && Number.isFinite(cuerpo.timestamp)
    ? new Date(cuerpo.timestamp)
    : undefined;
  let datos: unknown = cuerpo.payload ?? cuerpo;
  if (typeof datos === "string") {
    try {
      datos = JSON.parse(datos);
    } catch {
      throw solicitudInvalida("payload no es un JSON válido.");
    }
  }
  if (!datos || typeof datos !== "object" || Array.isArray(datos)) {
    throw solicitudInvalida("payload no es un objeto.");
  }
  const lectura = datos as Cuerpo;
  return {
    idModulo: enteroPositivo(lectura, "id_modulo"),
    estado: texto(lectura, "estado", 32),
    marcaTiempo,
  };
}

export const ingestaSensor: Manejador = async (req, deps) => {
  try {
    soloPost(req);
    exigirSecreto(req, HEADER_WEBHOOK, deps.secreto("WEBHOOK_SECRET"));
    const lectura = lecturaDeSensor(await leerCuerpo(req));
    const cajon = (await deps.cajones()).find((c) => moduloDeCajon(c) === lectura.idModulo);
    if (!cajon) {
      throw new ErrorHttp(404, "CAJON_NO_EXISTE", `No hay un cajón para el módulo ${lectura.idModulo}.`);
    }
    const r = await rpcConReintento<ResultadoIngesta>(deps, "registrar_lectura_sensor", {
      p_id_cajon: cajon.id_cajon,
      p_estado: lectura.estado,
    });

    const contexto: ContextoEvento = {
      origen: "sensor",
      cambioSensor: r.cambio_sensor,
      marcaTiempo: lectura.marcaTiempo,
    };
    const tareas = [propagarCajones(deps, [r.cajon], contexto)];
    if (r.conflicto) {
      // Decisión vigente: la lectura física manda y la reserva no se cancela; se avisa al administrador.
      console.warn(`Conflicto en ${r.cajon.etiqueta}: vehículo en un cajón ${r.conflicto}`);
      tareas.push(avisar(deps, { rol: "administrador" }, notificacionConflicto(r.cajon, r.conflicto)));
    }
    if (r.reserva_finalizada) {
      console.info(`RF-14: la reserva ${r.reserva_finalizada.id_reserva} finalizó al salir el vehículo`);
    }
    await Promise.all(tareas);
    return json(r);
  } catch (e) {
    return respuestaDeError(e);
  }
};

// --- barrido (Cron cada 5 s, solo si hay_trabajo_pendiente()) ---

export const barrido: Manejador = async (req, deps) => {
  try {
    soloPost(req);
    exigirSecreto(req, HEADER_CRON, deps.secreto("CRON_SECRET"));
    const r = await rpcConReintento<ResultadoBarrido>(deps, "barrido_reservas", {});
    await Promise.all([
      propagarCajones(deps, r.cajones, { origen: "sistema" }),
      notificarBarrido(deps, r),
    ]);
    return json({
      cajones: r.cajones.length,
      retrasos: r.retrasos.length,
      expiradas: r.expiradas.length,
      fin_proximo: r.fin_proximo.length,
      fin_alcanzado: r.fin_alcanzado.length,
    });
  } catch (e) {
    return respuestaDeError(e);
  }
};
