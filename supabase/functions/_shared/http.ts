// Respuestas, lectura y validación del cuerpo de la solicitud.

export class ErrorHttp extends Error {
  constructor(
    readonly status: number,
    readonly codigo: string,
    mensaje: string,
  ) {
    super(mensaje);
  }
}

export function json(cuerpo: unknown, status = 200): Response {
  return new Response(JSON.stringify(cuerpo), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

export function soloPost(req: Request): void {
  if (req.method !== "POST") {
    throw new ErrorHttp(405, "METODO_NO_PERMITIDO", "Usa POST.");
  }
}

export type Cuerpo = Record<string, unknown>;

/** Cuerpo JSON como objeto; vacío equivale a {}. */
export async function leerCuerpo(req: Request): Promise<Cuerpo> {
  const texto = await req.text();
  if (!texto.trim()) return {};
  try {
    const cuerpo = JSON.parse(texto);
    if (cuerpo && typeof cuerpo === "object" && !Array.isArray(cuerpo)) {
      return cuerpo as Cuerpo;
    }
  } catch {
    // cae al error de abajo
  }
  throw solicitudInvalida("El cuerpo de la solicitud no es un JSON válido.");
}

export function solicitudInvalida(mensaje: string): ErrorHttp {
  return new ErrorHttp(400, "SOLICITUD_INVALIDA", mensaje);
}

export function tokenBearer(req: Request): string | null {
  const valor = req.headers.get("Authorization") ?? "";
  const [tipo, token] = valor.split(" ");
  return tipo?.toLowerCase() === "bearer" && token ? token : null;
}

/** Compara en tiempo constante (no revela cuántos caracteres coinciden). */
export function secretoValido(recibido: string | null, esperado: string): boolean {
  if (recibido === null) return false;
  const a = new TextEncoder().encode(recibido);
  const b = new TextEncoder().encode(esperado);
  if (a.length !== b.length) return false;
  let diferencia = 0;
  for (let i = 0; i < a.length; i++) diferencia |= a[i] ^ b[i];
  return diferencia === 0;
}

export function exigirSecreto(req: Request, header: string, esperado: string): void {
  if (!secretoValido(req.headers.get(header), esperado)) {
    throw new ErrorHttp(401, "NO_AUTENTICADO", "Secreto inválido.");
  }
}

// --- Campos del cuerpo ---

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function enteroPositivo(cuerpo: Cuerpo, campo: string): number {
  const valor = cuerpo[campo];
  if (typeof valor !== "number" || !Number.isInteger(valor) || valor < 1 || valor > 32767) {
    throw solicitudInvalida(`${campo} debe ser un entero positivo.`);
  }
  return valor;
}

export function uuid(cuerpo: Cuerpo, campo: string): string {
  const valor = cuerpo[campo];
  if (typeof valor !== "string" || !UUID.test(valor)) {
    throw solicitudInvalida(`${campo} no es un identificador válido.`);
  }
  return valor;
}

/** Fecha ISO 8601 con zona; se envía tal cual a Postgres. */
export function fecha(cuerpo: Cuerpo, campo: string): string {
  const valor = cuerpo[campo];
  if (typeof valor !== "string" || Number.isNaN(Date.parse(valor))) {
    throw solicitudInvalida(`${campo} no es una fecha válida.`);
  }
  return valor;
}

export function texto(cuerpo: Cuerpo, campo: string, maximo = 256): string {
  const valor = cuerpo[campo];
  if (typeof valor !== "string" || !valor.trim() || valor.length > maximo) {
    throw solicitudInvalida(`${campo} es obligatorio.`);
  }
  return valor.trim();
}
