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
