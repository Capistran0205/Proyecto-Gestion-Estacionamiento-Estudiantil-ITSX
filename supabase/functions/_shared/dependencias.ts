// Implementación real de las dependencias (Supabase, EMQX, Firestore, FCM).
// Se crea una sola vez por worker y de forma perezosa: un secreto faltante
// solo afecta al efecto que lo usa.

import { createClient, type SupabaseClient } from "jsr:@supabase/supabase-js@2";
import { env, envOpcional, TOPICO_SISTEMA_BASE_DEFAULT } from "./config.ts";
import { type ConfigEmqx, publicarRetenido } from "./emqx.ts";
import { ErrorRpc, respuestaDeError } from "./errores.ts";
import { enviarPush } from "./fcm.ts";
import { COLECCION_EVENTOS, crearDocumento } from "./firestore.ts";
import { cuentaDesdeBase64, proveedorDeToken } from "./google.ts";
import type { CajonCatalogo, Dependencias, Destino, Manejador, Notificacion } from "./tipos.ts";

let instancia: Dependencias | null = null;

export function servir(manejador: Manejador): void {
  Deno.serve(async (req) => {
    let deps: Dependencias;
    try {
      deps = instancia ??= crearDependencias();
    } catch (e) {
      return respuestaDeError(e);
    }
    return await manejador(req, deps);
  });
}

function errorDe(e: { message: string; code?: string; hint?: string | null }): ErrorRpc {
  return new ErrorRpc(e.message, e.code, e.hint ?? undefined);
}

function crearDependencias(): Dependencias {
  const supabase = createClient(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"), {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  let catalogo: CajonCatalogo[] | null = null;
  let tokenGoogle: (() => Promise<string>) | null = null;

  const accessTokenGoogle = () =>
    (tokenGoogle ??= proveedorDeToken(cuentaDesdeBase64(env("FIREBASE_SERVICE_ACCOUNT_B64"))))();
  const emqx = (): ConfigEmqx => ({
    url: env("EMQX_API_URL"),
    clave: env("EMQX_API_KEY"),
    secreto: env("EMQX_API_SECRET"),
  });

  return {
    async rpc(nombre, args) {
      const { data, error } = await supabase.rpc(nombre, args);
      if (error) throw errorDe(error);
      return data;
    },

    async idUsuarioDelToken(token) {
      const { data, error } = await supabase.auth.getUser(token);
      if (error) {
        // Auth caído no es lo mismo que un token inválido.
        if ((error.status ?? 0) >= 500) throw error;
        return null;
      }
      return data.user?.id ?? null;
    },

    async rolDeUsuario(idUsuario) {
      const { data, error } = await supabase
        .from("usuarios")
        .select("rol")
        .eq("id_usuario", idUsuario)
        .eq("estado_cuenta", "activo")
        .maybeSingle();
      if (error) throw errorDe(error);
      return (data?.rol as string | undefined) ?? null;
    },

    async configuracion(claves) {
      const { data, error } = await supabase
        .from("config_sistema")
        .select("clave, valor")
        .in("clave", claves);
      if (error) throw errorDe(error);
      return Object.fromEntries((data ?? []).map((f) => [f.clave as string, f.valor as string]));
    },

    async cajones() {
      if (catalogo === null) {
        const { data, error } = await supabase.from("cajones").select("id_cajon, etiqueta");
        if (error) throw errorDe(error);
        catalogo = data as CajonCatalogo[];
      }
      return catalogo;
    },

    publicarRetenido: (topico, payload) => publicarRetenido(emqx(), topico, payload),

    async registrarEvento(evento) {
      await crearDocumento(env("FIREBASE_PROJECT_ID"), await accessTokenGoogle(), COLECCION_EVENTOS, evento);
    },

    async notificar(destino, notificacion) {
      const tokens = await tokensDe(supabase, destino);
      if (tokens.length === 0) return;
      const proyecto = env("FIREBASE_PROJECT_ID");
      const accessToken = await accessTokenGoogle();
      await Promise.all(
        tokens.map((token) => enviarAlDispositivo(supabase, proyecto, accessToken, token, notificacion)),
      );
    },

    topicoSistemaBase: () =>
      envOpcional("MQTT_TOPIC_SISTEMA_BASE", TOPICO_SISTEMA_BASE_DEFAULT).replace(/\/+$/, ""),

    secreto: (nombre) => env(nombre),
  };
}

async function tokensDe(supabase: SupabaseClient, destino: Destino): Promise<string[]> {
  let ids: string[];
  if ("idUsuario" in destino) {
    ids = [destino.idUsuario];
  } else {
    const { data, error } = await supabase
      .from("usuarios")
      .select("id_usuario")
      .eq("rol", destino.rol)
      .eq("estado_cuenta", "activo");
    if (error) throw errorDe(error);
    ids = (data ?? []).map((u) => u.id_usuario as string);
  }
  if (ids.length === 0) return [];
  const { data, error } = await supabase.from("dispositivos_fcm").select("token").in("id_usuario", ids);
  if (error) throw errorDe(error);
  return (data ?? []).map((d) => d.token as string);
}

/** Un reintento por dispositivo (reintentar el envío completo duplicaría avisos ya entregados). */
async function enviarAlDispositivo(
  supabase: SupabaseClient,
  proyecto: string,
  accessToken: string,
  token: string,
  notificacion: Notificacion,
): Promise<void> {
  for (let intento = 1; intento <= 2; intento++) {
    try {
      if ((await enviarPush(proyecto, accessToken, token, notificacion)) === "token_invalido") {
        console.info("Token FCM inválido; se elimina");
        await supabase.from("dispositivos_fcm").delete().eq("token", token);
      }
      return;
    } catch (e) {
      if (intento === 2) console.error(`No se pudo enviar la notificación ${notificacion.datos.tipo}:`, e);
    }
  }
}
