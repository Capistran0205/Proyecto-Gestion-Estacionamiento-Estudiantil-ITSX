# Pruebas unitarias — Módulo del Administrador (reservas y escáner QR)

Sistema de Estacionamiento Estudiantil · App móvil (Flet + MVVM) · Fase 2, Módulo C
Fecha de ejecución: 2026-11-20 · Comando: `uv run pytest`

El módulo tiene dos pantallas, solo para el rol administrador:
- **Reservas** (`/admin/reservas`): lista de reservas vigentes. Se abre desde la tarjeta "Reservas" de Inicio.
- **Escanear QR** (`/admin/escanear`): confirma la llegada del estudiante. Se abre desde Reservas.

Todas las pruebas usan mocks: no se conectan a Supabase, a las Edge Functions ni a la cámara reales. El lector de QR sí usa OpenCV de verdad, con imágenes generadas con `segno`. La hora se fija con un reloj falso (10:30, hora de México).

## Resultado

| Archivo del módulo | Capa | Archivo de prueba | Pruebas | Pasaron | Fallaron |
|---|---|---|---|---|---|
| `src/parking_app/viewmodels/admin_reservas_viewmodel.py` | ViewModel | `tests/test_admin.py` | 8 | 8 | 0 |
| `src/parking_app/views/admin_reservas_view.py` | View | `tests/test_admin.py` | 1 | 1 | 0 |
| `src/parking_app/viewmodels/escaner_viewmodel.py` | ViewModel | `tests/test_admin.py` | 13 | 13 | 0 |
| `src/parking_app/views/escaner_view.py` | View | `tests/test_admin.py` | 1 | 1 | 0 |
| `src/parking_app/services/lector_qr.py` | Service | `tests/test_lector_qr.py` | 4 | 4 | 0 |
| `src/parking_app/services/reservas_service.py` (`confirmar_llegada`, `reservas_activas`, `reserva_por_codigo`) | Service | `tests/test_reservas_service.py` (solo las del administrador) | 5 | 5 | 0 |
| `src/parking_app/viewmodels/inicio_viewmodel.py` (sin tarjeta "Mi reserva") | ViewModel | `tests/test_inicio.py` | 1 | 1 | 0 |
| `src/parking_app/router.py` (guardia de rol y pila de pantallas) | Navegación | `tests/test_router.py` | 3 | 3 | 0 |
| `src/parking_app/router.py` (aviso push de conflicto) | Navegación | `tests/test_router_notificaciones.py` | 2 | 2 | 0 |
| **Total** | | | **38** | **38** | **0** |

Suite completa del proyecto: 427 de 427 pruebas pasan.

La prueba `test_el_administrador_no_ve_la_tarjeta` de `test_inicio.py` también aparece en `PruebasModuloReservaCajon.md`. La prueba de `reglas()` (Edge Function `reglas-reserva`), que el administrador usa para calcular la tolerancia, está contada en ese mismo documento.

## Flujo que cubren

### Reservas del administrador
1. El router solo deja entrar a `/admin/reservas` y `/admin/escanear` con rol administrador. Un estudiante se queda en Inicio.
2. `reservas_service.reservas_activas()` lee las reservas `pendiente_llegada` y `en_uso`, ordenadas por hora y **sin el código QR**.
3. El ViewModel las agrupa en tres fases y muestra un contador por cada una:
   - **Por llegar:** tiempo que le queda al estudiante para llegar.
   - **En tolerancia:** ya pasó su hora; tiempo que queda de tolerancia.
   - **En uso:** tiempo hasta la hora de salida.
4. La tolerancia se toma de `reglas-reserva` (`config_sistema`). Si no se pudo leer, la app muestra `--:--` en lugar de inventar un valor.
5. La lista se vuelve a consultar cuando MQTT reporta un cambio en `reserva1/+` y al regresar del escáner. Un tic del reloj sin cambios no genera una consulta.

### Escáner QR
1. En el teléfono, `flet-camera` entrega cuadros JPEG y `LectorQr` (OpenCV) busca un QR. En la PC no hay cámara y el código se escribe a mano.
2. Solo un texto con el formato del sistema (32 caracteres hexadecimales en minúscula) se envía al servidor. Un QR ajeno se rechaza sin hacer la petición.
3. `reservas_service.confirmar_llegada(codigo)` llama a la Edge Function `confirmar-llegada`, que registra la llegada y arranca el cronómetro de uso.
4. Si el backend rechaza el código (`QR_EXPIRADO`, `QR_USADO`, `QR_CANCELADO`, `QR_INVALIDO`), la app consulta la reserva con `reserva_por_codigo` para mostrar el motivo y los datos.
5. Desde el resultado se puede escanear otro código o volver a la lista de reservas.

### Aviso de conflicto
Si el sensor detecta un vehículo en un cajón reservado, el backend envía un push a los administradores (`conflicto_sensor`). Al tocarlo, se abre la pantalla de Reservas.

## Detalle por archivo

### `test_admin.py` — 23 pruebas

**Reservas — ViewModel (8)**
- Contadores por fase: 1 por llegar, 1 en tolerancia y 1 en uso.
- Filas como el mockup:
  - C1 "Por llegar", "Reserva 11:00 a 14:00", tiempo `12:30`.
  - C3 "En tolerancia", "Retraso · Reserva 11:00 a 14:00", tiempo `15:00` (pasó su hora hace 5 min, con 20 de tolerancia).
  - C2 "En uso", "Llegó a las 10:05 · Sale 14:00", tiempo `03:30`.
- Sin reglas del backend, la fila en tolerancia muestra `--:--` y no aparece ninguna alerta.
- Sin reservas, la lista se marca como vacía.
- Error de red al cargar: "No se pudo conectar".
- El botón "Escanear" llama a la navegación del escáner.
- La lista se consulta otra vez cuando MQTT cambia un cajón (`reservado`). Un tic del reloj sin cambios no consulta, y después de liberar el ViewModel ya no escucha.
- Al confirmar la salida con el vehículo todavía dentro, el estado del cajón no cambia, pero el backend vuelve a publicar `liberado` en `reserva1/1` y eso basta para que la lista se actualice.

**Reservas — View (1)**
- Los tres contadores muestran "1", la lista tiene 3 filas y no se ven los avisos de "vacía" ni "cargando".

**Escáner — ViewModel (13)**
- Un cuadro con QR válido registra la llegada. El resultado como el mockup:
  - "Código válido" · "Se registró la llegada del estudiante."
  - Cajón C1, "Llegada registrada a las 10:58".
  - Tabla: Reserva `#5B1F6C1E`, Horario reservado 11:00 a 14:00, Medio de transporte "Automóvil", Estado "Cronómetro de uso iniciado".
- Un cuadro sin QR sigue escaneando y no llama al servidor.
- Un QR ajeno (`https://ejemplo.com`) no va al servidor: "Código no reconocido".
- Rechazos con motivo y datos (4 casos). Todos muestran "Código rechazado" · "No se registró ninguna llegada." y la tabla empieza con la reserva y el cajón:
  - `QR_EXPIRADO` → "Código expirado", última fila "Expiró a las 10:20".
  - `QR_USADO` → "Código ya utilizado", "Llegada registrada 10:30".
  - `QR_CANCELADO` → "Reserva cancelada", "Cancelada a las 10:30".
  - `QR_CANCELADO` sin hora de cancelación guardada (reservas anteriores a esa columna) → muestra el horario reservado.
- Código expirado sin datos de la reserva: el motivo menciona la "tolerancia de 20 minutos" que informa el backend.
- Código inexistente (`QR_INVALIDO`): "Código no reconocido", sin consultar la reserva.
- Sin conexión: "No se pudo validar" y pide volver a escanear. Avisa que, si la llegada sí alcanzó a registrarse, el código aparecerá como "ya utilizado" (no se registra dos veces).
- Cancelar una validación en curso vuelve a escanear sin resultado.
- "Escanear otro" limpia el resultado; "Ver reservas" regresa a la lista.
- La linterna se enciende y se apaga sola al validar.

**Escáner — View (1)**
- En la PC (sin cámara) se ve el campo para escribir el código y no se ve el botón de linterna. El título dice "Escanear QR".
- Al validar a mano cambia a "Resultado" con 6 elementos: círculo, títulos, cajón y tabla.
- Un código rechazado también muestra 6 elementos: círculo, títulos, motivo y tabla.

### `test_lector_qr.py` — 4 pruebas
- Lee el código de una reserva desde una imagen de 1280 px con el QR en medio, como un cuadro de la cámara. El lector la reduce a 720 px antes de buscar.
- Una imagen sin QR devuelve `None`.
- Bytes que no son imagen devuelven `None`, sin lanzar error.
- `es_codigo_del_sistema` acepta 32 hexadecimales en minúscula y rechaza una URL o el mismo código en mayúsculas.

### `test_reservas_service.py` — 5 pruebas del administrador
- `confirmar_llegada` envía `{"codigo_qr": ...}` y lee el cajón (C1), el medio de transporte y el nombre del estudiante ("Ana Pérez").
- Un QR rechazado (409) se convierte en `ReservaError` con su código (`QR_USADO`).
- `reservas_activas` filtra `pendiente_llegada` y `en_uso`, ordena por `fecha_usuario` y **no pide `codigo_qr`**. Lee la etiqueta del cajón (C3).
- `reserva_por_codigo` busca por `codigo_qr`, pide `fecha_cancelacion` y la interpreta (reserva cancelada a las 16:30 UTC).
- Una reserva sin `fecha_cancelacion` la deja en `None`.

### `test_inicio.py` — 1 prueba
- El administrador no ve la tarjeta "Mi reserva" y no se consulta ninguna reserva suya.

### `test_router.py` — 3 pruebas
- Un estudiante no entra a `/admin/reservas` ni a `/admin/escanear`: se queda en `/inicio`.
- El administrador llega a Reservas desde la tarjeta de Inicio y al escáner desde Reservas (`/inicio` → `/admin/reservas` → `/admin/escanear`). En la PC no se crea la cámara. "Ver reservas" regresa a la lista e ir a Inicio limpia la pila.
- Al volver del escáner con el gesto de regresar, la lista de reservas se consulta otra vez. Mientras el escáner está abierto no se consulta.

### `test_router_notificaciones.py` — 2 pruebas
- Tocar el aviso `conflicto_sensor` lleva al administrador a `/admin/reservas`.
- Otros avisos (p. ej. `retraso_llegada`) no lo mueven de Inicio.

## Pruebas del backend (Deno) que no se ejecutaron

`supabase/functions/_tests/operaciones.test.ts` tiene 4 pruebas relacionadas con el administrador. No se ejecutaron porque Deno no está instalado en este equipo, así que no están en el conteo:
- Un estudiante no puede confirmar llegadas (403, sin llamar a la base de datos).
- El administrador confirma con el id de su JWT, el código se recorta y el evento queda con origen "administrador".
- Un QR expirado se reporta con su motivo (409).
- Un vehículo en un cajón reservado envía el aviso `conflicto_sensor` a los administradores. La lectura física manda, pero el retain de `reserva1/3` sigue diciendo "reservado".

Para correrlas: `deno test supabase/functions/_tests/`.

## Observaciones

- **La cámara real no tiene prueba automática.** `flet-camera` solo funciona en el teléfono; las pruebas cubren el lector con imágenes generadas y el escáner con entrada manual. La lectura con cámara se validó a mano en Android (≤ 3 s con resolución Media).
- **La tarjeta "Reservas" de Inicio no tiene prueba de vista.** La prueba del router comprueba que el administrador llega a la lista desde Inicio (`ir_a_reservas`), pero no que la tarjeta se muestre solo a ese rol.
