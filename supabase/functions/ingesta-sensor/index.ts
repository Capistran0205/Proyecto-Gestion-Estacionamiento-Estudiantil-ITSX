import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { servir } from "../_shared/dependencias.ts";
import { ingestaSensor } from "../_shared/operaciones.ts";

servir(ingestaSensor);
