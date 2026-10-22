import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { servir } from "../_shared/dependencias.ts";
import { extenderReserva } from "../_shared/operaciones.ts";

servir(extenderReserva);
