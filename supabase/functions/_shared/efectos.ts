// Efectos después de cada rpc: publicar el estado_sistema de cada cajón en
// MQTT y registrar el evento en Firestore cuando hubo cambio. La base de datos
// ya confirmó la transacción y manda: si un efecto falla se registra y se
// reintenta una vez, pero la operación no se revierte ni se reporta como fallida.

import type { CajonRecalculado, Dependencias, Destino, Notificacion, OrigenEvento } from "./tipos.ts";

export interface ContextoEvento {
  origen: OrigenEvento;
  /** Ingesta: la lectura del sensor cambió aunque el estado efectivo no. */
  cambioSensor?: boolean;
  /** Momento del evento; en la ingesta, el timestamp del mensaje en EMQX. Por defecto, ahora. */
  marcaTiempo?: Date;
}

/** Ejecuta la acción y, si falla, la reintenta una vez. Nunca lanza. */
export async function conReintento(descripcion: string, accion: () => Promise<unknown>): Promise<boolean> {
  for (let intento = 1; intento <= 2; intento++) {
    try {
      await accion();
      return true;
    } catch (e) {
      if (intento === 1) {
        console.warn(`${descripcion} falló; se reintenta una vez:`, e);
      } else {
        console.error(`${descripcion} falló de nuevo (la base de datos ya quedó actualizada):`, e);
      }
    }
  }
  return false;
}

/** Notifica sin lanzar: un aviso fallido no debe afectar la respuesta. */
export async function avisar(deps: Dependencias, destino: Destino, notificacion: Notificacion): Promise<void> {
  try {
    await deps.notificar(destino, notificacion);
  } catch (e) {
    console.error(`No se pudo enviar la notificación ${notificacion.datos.tipo}:`, e);
  }
}

/** "C3" → 3 (el número de módulo de la ESP32); si la etiqueta no sigue el formato, el id. */
export function moduloDeCajon(cajon: { id_cajon: number; etiqueta?: string | null }): number {
  const coincidencia = /^C(\d+)$/i.exec(cajon.etiqueta ?? "");
  return coincidencia ? Number(coincidencia[1]) : cajon.id_cajon;
}

export function topicoDeModulo(deps: Dependencias, modulo: number): string {
  return `${deps.topicoSistemaBase()}/${modulo}`;
}

export async function propagarCajones(
  deps: Dependencias,
  cajones: CajonRecalculado[],
  contexto: ContextoEvento,
): Promise<void> {
  // Si un cajón aparece dos veces, el último resultado es el vigente.
  const unicos = new Map<number, CajonRecalculado>();
  for (const cajon of cajones) unicos.set(cajon.id_cajon, cajon);
  const marcaTiempo = contexto.marcaTiempo ?? new Date();

  await Promise.all([...unicos.values()].flatMap((cajon) => {
    const modulo = moduloDeCajon(cajon);
    const tareas = [
      // Siempre: el retain es idempotente y corrige a quien tenga un estado viejo.
      conReintento(`Publicar ${cajon.etiqueta} en MQTT`, () =>
        deps.publicarRetenido(
          topicoDeModulo(deps, modulo),
          JSON.stringify({ id_modulo: modulo, estado: cajon.estado_sistema }),
        )),
    ];
    if (cajon.cambio || contexto.cambioSensor) {
      // Esquema de configuracion_firestore_fcm.md (paso 3); estado_nuevo con los
      // valores del enum de Supabase (no_conectado con guion bajo).
      tareas.push(conReintento(`Registrar el evento de ${cajon.etiqueta} en Firestore`, () =>
        deps.registrarEvento({
          id_cajon: cajon.id_cajon,
          etiqueta: cajon.etiqueta,
          estado_nuevo: cajon.estado_nuevo,
          origen_evento: contexto.origen,
          marca_tiempo: marcaTiempo,
        })));
    }
    return tareas;
  }));
}
