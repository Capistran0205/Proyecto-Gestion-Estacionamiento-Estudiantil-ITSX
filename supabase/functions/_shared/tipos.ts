// Tipos compartidos por las Edge Functions.

/** Lo que se publica en reserva1/{id_modulo}. */
export type EstadoSistema = "bloqueado" | "reservado" | "liberado";

/** origen_evento de los eventos en Firestore. */
export type OrigenEvento = "sensor" | "sistema" | "administrador";

/** Objeto que devuelve la función SQL recalcular_estado_cajon. */
export interface CajonRecalculado {
  id_cajon: number;
  etiqueta: string;
  estado_anterior: string | null;
  estado_nuevo: string;
  cambio: boolean;
  estado_sensor: string;
  estado_sistema: EstadoSistema;
}

export interface CajonCatalogo {
  id_cajon: number;
  etiqueta: string;
}

export interface Notificacion {
  titulo: string;
  cuerpo: string;
  /** FCM solo admite cadenas en `data`. Siempre lleva `tipo` y, si aplica, `id_reserva`. */
  datos: Record<string, string>;
}

export type Destino = { idUsuario: string } | { rol: "administrador" };

export type NombreSecreto = "WEBHOOK_SECRET" | "CRON_SECRET";

/** Todo lo externo que usan las funciones; en las pruebas se reemplaza por dobles. */
export interface Dependencias {
  /** Llama una función SQL con service_role. Lanza ErrorRpc si falla. */
  rpc(nombre: string, args: Record<string, unknown>): Promise<unknown>;
  /** id del usuario dueño de un JWT válido, o null si el token no es válido. */
  idUsuarioDelToken(token: string): Promise<string | null>;
  rolDeUsuario(idUsuario: string): Promise<string | null>;
  /** Valores de config_sistema (la app no puede leer esa tabla). */
  configuracion(claves: string[]): Promise<Record<string, string>>;
  /** Catálogo id_cajon ↔ etiqueta (se guarda en memoria del worker). */
  cajones(): Promise<CajonCatalogo[]>;
  publicarRetenido(topico: string, payload: string): Promise<void>;
  registrarEvento(evento: Record<string, unknown>): Promise<void>;
  notificar(destino: Destino, notificacion: Notificacion): Promise<void>;
  topicoSistemaBase(): string;
  secreto(nombre: NombreSecreto): string;
}

export type Manejador = (req: Request, deps: Dependencias) => Promise<Response>;
