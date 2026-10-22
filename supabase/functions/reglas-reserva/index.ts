import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { servir } from "../_shared/dependencias.ts";
import { reglasReserva } from "../_shared/operaciones.ts";

servir(reglasReserva);
