# Sistema de Estacionamiento Estudiantil

App móvil (Flet + MVVM) para consultar la ocupación de los cajones en tiempo real.

## Requisitos

- [uv](https://docs.astral.sh/uv/) y Python 3.13
- Archivo `.env` en la raíz con las variables listadas en `CLAUDE.MD`

```powershell
uv sync
```

## Ejecutar

**En el teléfono (Android)**: App de prueba, se conecta el teléfono
a la una red Wi-Fi para visualizar la ocupación de los cajones de estacionamiento:

```powershell
uv run flet run --android --name estacionamiento main.py
```

Escanea el código QR de la terminal con la app Flet.

> `--name` es obligatorio aquí: sin él, Flet publica la app en una ruta que incluye
> el nombre de la carpeta del proyecto, y como tiene espacios la URL del QR se corta
> y el teléfono recibe un error 404.

**En la computadora** (ventana de escritorio):

```powershell
uv run main.py
```

## Pruebas

```powershell
uv run pytest
```

Backend (Edge Functions, sin red real; Deno se descarga con `npx`):

```powershell
cd supabase/functions
npx -y deno@2 test --node-modules-dir=none --no-lock _tests/
```

## Fase 2: migrar el ACL de EMQX

Da a los usuarios ya registrados permiso de suscribirse a `reserva1/+`.
Sin `--aplicar` solo muestra los cambios:

```powershell
uv run python scripts/migrar_acl_emqx.py --esp32 <usuario_mqtt_de_la_esp32>
uv run python scripts/migrar_acl_emqx.py --esp32 <usuario_mqtt_de_la_esp32> --aplicar
```
