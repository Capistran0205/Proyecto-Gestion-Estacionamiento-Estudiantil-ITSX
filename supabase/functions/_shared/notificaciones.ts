// Contenido de las notificaciones push. Todas llevan `tipo` e `id_reserva` en
// `data` para que la app abra la pantalla de la reserva.

import { ZONA_HORARIA } from "./config.ts";
import { avisar, moduloDeCajon } from "./efectos.ts";
import type { CajonCatalogo, CajonRecalculado, Dependencias, Notificacion } from "./tipos.ts";

export interface AvisoReserva {
  id_reserva: string;
  id_usuario: string;
  id_cajon: number;
  tolerancia_hasta?: string;
  fecha_fin?: string;
}

export interface ResultadoBarrido {
  cajones: CajonRecalculado[];
  retrasos: AvisoReserva[];
  expiradas: AvisoReserva[];
  fin_proximo: AvisoReserva[];
  fin_alcanzado: AvisoReserva[];
}

export type TipoNotificacion =
  | "retraso_llegada"
  | "reserva_expirada"
  | "fin_proximo"
  | "fin_alcanzado"
  | "conflicto_sensor";

const formatoHora = new Intl.DateTimeFormat("es-MX", {
  timeZone: ZONA_HORARIA,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function horaLocal(iso: string | undefined): string {
  return iso ? formatoHora.format(new Date(iso)) : "";
}

export function etiquetaDe(catalogo: CajonCatalogo[], idCajon: number): string {
  return catalogo.find((c) => c.id_cajon === idCajon)?.etiqueta ?? `C${idCajon}`;
}

function datos(tipo: TipoNotificacion, aviso: AvisoReserva): Record<string, string> {
  return { tipo, id_reserva: aviso.id_reserva, id_cajon: String(aviso.id_cajon) };
}

// RF-07
export function notificacionRetraso(aviso: AvisoReserva, etiqueta: string): Notificacion {
  return {
    titulo: "Se terminó tu tiempo de llegada",
    cuerpo: `Tienes hasta las ${horaLocal(aviso.tolerancia_hasta)} para llegar al cajón ${etiqueta}; ` +
      "después tu reserva se cancelará.",
    datos: datos("retraso_llegada", aviso),
  };
}

// RF-08
export function notificacionExpirada(aviso: AvisoReserva, etiqueta: string): Notificacion {
  return {
    titulo: "Tu reserva se canceló",
    cuerpo: `No llegaste a tiempo al cajón ${etiqueta}. La reserva se canceló y su código QR ya no es válido.`,
    datos: datos("reserva_expirada", aviso),
  };
}

// RF-12
export function notificacionFinProximo(aviso: AvisoReserva, etiqueta: string): Notificacion {
  return {
    titulo: "Tu reserva está por terminar",
    cuerpo: `Tu reserva del cajón ${etiqueta} termina a las ${horaLocal(aviso.fecha_fin)}. ` +
      "Puedes extenderla una hora desde la app.",
    datos: { ...datos("fin_proximo", aviso), accion: "extender" },
  };
}

// RF-13: al llegar fecha_fin solo se avisa; la reserva sigue en uso.
export function notificacionFinAlcanzado(aviso: AvisoReserva, etiqueta: string): Notificacion {
  return {
    titulo: "Terminó el horario de tu reserva",
    cuerpo: `Tu reserva del cajón ${etiqueta} terminó a las ${horaLocal(aviso.fecha_fin)}. ` +
      "Confirma tu salida en la app al retirar tu vehículo.",
    datos: datos("fin_alcanzado", aviso),
  };
}

export function notificacionConflicto(cajon: CajonRecalculado, conflicto: string): Notificacion {
  const situacion = conflicto === "reservado" ? "estaba reservado" : "alguien lo estaba reservando";
  return {
    titulo: `Vehículo en el cajón ${cajon.etiqueta}`,
    cuerpo: `El sensor detectó un vehículo en el cajón ${cajon.etiqueta}, que ${situacion}.`,
    datos: {
      tipo: "conflicto_sensor",
      id_cajon: String(cajon.id_cajon),
      id_modulo: String(moduloDeCajon(cajon)),
      conflicto,
    },
  };
}

export async function notificarBarrido(deps: Dependencias, r: ResultadoBarrido): Promise<void> {
  const avisos: [AvisoReserva[], (a: AvisoReserva, etiqueta: string) => Notificacion][] = [
    [r.retrasos, notificacionRetraso],
    [r.expiradas, notificacionExpirada],
    [r.fin_proximo, notificacionFinProximo],
    [r.fin_alcanzado, notificacionFinAlcanzado],
  ];
  if (avisos.every(([lista]) => lista.length === 0)) return;
  const catalogo = await deps.cajones().catch((e) => {
    console.warn("No se pudo leer el catálogo de cajones para las notificaciones:", e);
    return [];
  });
  await Promise.all(avisos.flatMap(([lista, crear]) =>
    lista.map((aviso) =>
      avisar(deps, { idUsuario: aviso.id_usuario }, crear(aviso, etiquetaDe(catalogo, aviso.id_cajon)))
    )
  ));
}
