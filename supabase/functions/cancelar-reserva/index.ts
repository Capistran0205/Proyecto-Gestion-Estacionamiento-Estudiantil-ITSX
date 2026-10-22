import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { servir } from "../_shared/dependencias.ts";
import { cancelarReserva } from "../_shared/operaciones.ts";

servir(cancelarReserva);
