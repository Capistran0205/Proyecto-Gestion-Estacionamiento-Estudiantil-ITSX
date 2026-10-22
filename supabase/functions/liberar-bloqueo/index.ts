import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { servir } from "../_shared/dependencias.ts";
import { liberarBloqueo } from "../_shared/operaciones.ts";

servir(liberarBloqueo);
