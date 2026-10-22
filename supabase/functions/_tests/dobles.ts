// Dobles de prueba de las dependencias externas (sin red).

import { ErrorRpc } from "../_shared/errores.ts";
import type {
  CajonCatalogo,
  CajonRecalculado,
  Dependencias,
  Destino,
  EstadoSistema,
  Notificacion,
} from "../_shared/tipos.ts";

export const TOPICO_BASE = "infraestructura/pruebaiot/reserva1";
export const WEBHOOK = "secreto-webhook";
export const CRON = "secreto-cron";

type Respuesta = unknown | ErrorRpc | Error;

export class DepsFalsas implements Dependencias {
  usuarios: Record<string, string> = { "token-ana": "uid-ana", "token-admin": "uid-admin" };
  roles: Record<string, string> = { "uid-ana": "estudiante", "uid-admin": "administrador" };
  catalogo: CajonCatalogo[] = [1, 2, 3, 4].map((i) => ({ id_cajon: i, etiqueta: `C${i}` }));

  /** Respuestas de rpc en orden; un Error se lanza. */
  respuestas: Respuesta[] = [];
  llamadasRpc: { nombre: string; args: Record<string, unknown> }[] = [];
  publicaciones: { topico: string; payload: Record<string, unknown> }[] = [];
  eventos: Record<string, unknown>[] = [];
  notificaciones: { destino: Destino; notificacion: Notificacion }[] = [];
  fallasPublicar = 0;
  fallasEvento = 0;

  rpc(nombre: string, args: Record<string, unknown>): Promise<unknown> {
    this.llamadasRpc.push({ nombre, args });
    const respuesta = this.respuestas.shift();
    if (respuesta instanceof Error) return Promise.reject(respuesta);
    return Promise.resolve(respuesta);
  }

  idUsuarioDelToken(token: string): Promise<string | null> {
    return Promise.resolve(this.usuarios[token] ?? null);
  }

  rolDeUsuario(idUsuario: string): Promise<string | null> {
    return Promise.resolve(this.roles[idUsuario] ?? null);
  }

  config: Record<string, string> = {
    cronometro_llegada_min: "60",
    tolerancia_min: "20",
    aviso_fin_min: "10",
    duracion_max_h: "15",
  };
  fallaConfig = false;

  configuracion(claves: string[]): Promise<Record<string, string>> {
    if (this.fallaConfig) return Promise.reject(new Error("BD caída"));
    return Promise.resolve(Object.fromEntries(claves.map((c) => [c, this.config[c]])));
  }

  cajones(): Promise<CajonCatalogo[]> {
    return Promise.resolve(this.catalogo);
  }

  publicarRetenido(topico: string, payload: string): Promise<void> {
    if (this.fallasPublicar-- > 0) return Promise.reject(new Error("EMQX caído"));
    this.publicaciones.push({ topico, payload: JSON.parse(payload) });
    return Promise.resolve();
  }

  registrarEvento(evento: Record<string, unknown>): Promise<void> {
    if (this.fallasEvento-- > 0) return Promise.reject(new Error("Firestore caído"));
    this.eventos.push(evento);
    return Promise.resolve();
  }

  notificar(destino: Destino, notificacion: Notificacion): Promise<void> {
    this.notificaciones.push({ destino, notificacion });
    return Promise.resolve();
  }

  topicoSistemaBase(): string {
    return TOPICO_BASE;
  }

  secreto(nombre: "WEBHOOK_SECRET" | "CRON_SECRET"): string {
    return nombre === "WEBHOOK_SECRET" ? WEBHOOK : CRON;
  }
}

export function cajon(
  id: number,
  opciones: { cambio?: boolean; sistema?: EstadoSistema; nuevo?: string; etiqueta?: string } = {},
): CajonRecalculado {
  return {
    id_cajon: id,
    etiqueta: opciones.etiqueta ?? `C${id}`,
    estado_anterior: "libre",
    estado_nuevo: opciones.nuevo ?? "bloqueado",
    cambio: opciones.cambio ?? true,
    estado_sensor: "libre",
    estado_sistema: opciones.sistema ?? "bloqueado",
  };
}

export function solicitud(
  cuerpo: unknown,
  opciones: { token?: string; headers?: Record<string, string>; metodo?: string } = {},
): Request {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...opciones.headers };
  if (opciones.token) headers.Authorization = `Bearer ${opciones.token}`;
  return new Request("http://localhost/fn", {
    method: opciones.metodo ?? "POST",
    headers,
    body: opciones.metodo === "GET" ? undefined : JSON.stringify(cuerpo),
  });
}

/** Silencia los logs esperados de las pruebas de fallas. */
export async function sinLogs<T>(accion: () => Promise<T>): Promise<T> {
  const originales = { warn: console.warn, error: console.error, info: console.info };
  console.warn = console.error = console.info = () => {};
  try {
    return await accion();
  } finally {
    Object.assign(console, originales);
  }
}
