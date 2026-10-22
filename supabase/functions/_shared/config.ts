// Lectura de secretos (supabase secrets set ... / variables del runtime).

export function env(nombre: string): string {
  const valor = Deno.env.get(nombre)?.trim();
  if (!valor) {
    throw new Error(`Falta el secreto ${nombre} en la Edge Function`);
  }
  return valor;
}

export function envOpcional(nombre: string, porDefecto: string): string {
  return Deno.env.get(nombre)?.trim() || porDefecto;
}

/** Solo para mostrar horas en las notificaciones; las reglas viven en config_sistema. */
export const ZONA_HORARIA = "America/Mexico_City";

export const TOPICO_SISTEMA_BASE_DEFAULT = "infraestructura/pruebaiot/reserva1";

/** Headers con los que la regla de EMQX y el Cron se autentican. */
export const HEADER_WEBHOOK = "x-webhook-secret";
export const HEADER_CRON = "x-cron-secret";
