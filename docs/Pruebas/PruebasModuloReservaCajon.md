# Pruebas unitarias — Módulo de Reserva de cajón

Sistema de Estacionamiento Estudiantil · App móvil (Flet + MVVM) · Fase 2, Módulo B
Fecha de ejecución: 2026-11-19 · Comando: `uv run pytest`

El módulo tiene dos pantallas para el estudiante y una tarjeta en el menú:
- **Reservar** (`/reservar`): flujo de 3 pasos que se abre al tocar un cajón libre en el mapa de ocupación.
- **Mi reserva** (`/mi-reserva`): QR, cuenta regresiva, cancelar, extender y confirmar salida.
- **Tarjeta "Mi reserva"** en el menú principal.

Todas las pruebas usan mocks: no se conectan a Supabase, a las Edge Functions ni al broker reales. Las peticiones HTTP se simulan con `httpx.MockTransport` y el tiempo con un reloj falso.

## Resultado

| Archivo del módulo | Capa | Archivo de prueba | Pruebas | Pasaron | Fallaron |
|---|---|---|---|---|---|
| `src/parking_app/viewmodels/reservar_viewmodel.py` | ViewModel | `tests/test_reservar.py` | 20 | 20 | 0 |
| `src/parking_app/views/reservar_view.py` | View | `tests/test_reservar.py` | 3 | 3 | 0 |
| `src/parking_app/viewmodels/ocupacion_viewmodel.py` (`reservar`) | ViewModel | `tests/test_reservar.py` | 1 | 1 | 0 |
| `src/parking_app/viewmodels/mi_reserva_viewmodel.py` (+ `aviso_cambios.py`) | ViewModel | `tests/test_mi_reserva.py` | 34 | 34 | 0 |
| `src/parking_app/views/mi_reserva_view.py` (+ `components/codigo_qr.py`) | View | `tests/test_mi_reserva.py` | 5 | 5 | 0 |
| `src/parking_app/services/reservas_service.py` (funciones del estudiante) + `models/reserva_cajon.py` | Service / Model | `tests/test_reservas_service.py` | 21 | 21 | 0 |
| `src/parking_app/services/almacen_reserva.py` | Service | `tests/test_reservas_service.py` | 2 | 2 | 0 |
| `src/parking_app/viewmodels/inicio_viewmodel.py` + `views/inicio_view.py` (tarjeta "Mi reserva") | ViewModel / View | `tests/test_inicio.py` | 7 | 7 | 0 |
| `src/parking_app/router.py` (rutas de reserva) | Navegación | `tests/test_router.py` | 3 | 3 | 0 |
| `src/parking_app/router.py` (avisos push que abren "Mi reserva") | Navegación | `tests/test_router_notificaciones.py` | 5 | 5 | 0 |
| **Total** | | | **101** | **101** | **0** |

Suite completa del proyecto: 427 de 427 pruebas pasan.

Las pruebas del estado efectivo del cajón (cuándo se ve libre, bloqueado o reservado) están en `PruebasModuloOcupacionCajones.md`. Las de `reservas_service` que usa el administrador (confirmar llegada, lista de reservas, códigos rechazados) se dejan para el documento del Módulo C.

## Flujo que cubren

### Reservar (máximo 3 pasos, RNF-04)
1. **Elegir cajón:** al tocar un cajón libre en el mapa, la app llama a `bloquear-cajon`, que lo aparta (se ve "bloqueado") y devuelve:
   - La hora de inicio fija: la siguiente hora en punto.
   - Las reglas de llegada y tolerancia.
2. **Horario:** solo se ofrecen horas de fin válidas, hasta las 22:00, y se muestra la duración.
3. **Confirmar:** un resumen con las reglas del backend. `crear-reserva` crea la reserva y la app la guarda en el teléfono para poder verla sin internet (RNF-08).

Si el estudiante sale o cancela en los pasos 1–2, se llama a `liberar-bloqueo`. Las reglas de horario y duración las aplica la base de datos: la app solo muestra el motivo del rechazo.

### Mi reserva
- **Fases:** confirmada (tiempo para llegar) → con retraso (tolerancia restante, en naranja) → expirada. Además: cancelada, en uso y salida confirmada.
- **QR** generado en el teléfono a partir de `codigo_qr`; se sigue mostrando sin internet.
- **En uso:** tiempo restante, aviso de fin próximo, "Extender 1 hora" y "Confirmar salida".
- **Actualización:** consulta cada 30 s y, además, en cuanto MQTT reporta un cambio en su cajón (`AvisoDeCambios`).

## Detalle por archivo

### `test_reservar.py` — 24 pruebas

**Paso 1 — Elegir cajón (ViewModel)**
- Tocar un cajón en el mapa lo aparta al entrar: C3 queda "Bloqueado", seleccionado y "Seleccionado para reservar".
- Solo los cajones libres se pueden tocar.
- Un cajón apartado por otro estudiante se ve bloqueado y no se puede tocar.
- Continuar sin cajón: "Elige un cajón libre".
- Rechazo al apartar: "No se pudo apartar el cajón" con el motivo del backend, sin cajón seleccionado.
- Con reserva activa en el servidor se muestra el aviso "Ya tienes una reserva activa".
- Si la reserva está guardada en el teléfono, no se consulta la red: se muestra el aviso y el botón para verla.
- Una reserva guardada con la tolerancia ya vencida se ignora y se aparta el cajón normalmente.
- Sin conexión: "No se pudo conectar".
- Si el servidor responde con error (p. ej. función no desplegada): "El servicio de reservas no está disponible", sin culpar a la conexión del estudiante.

**Pasos 2 y 3 — Horario y confirmación (ViewModel)**
- Horario: inicio fijo a las 11:00, 11 opciones de fin (12:00 a 22:00), duración mínima por omisión "1 h" y se actualiza al elegir (p. ej. "3 h").
- El resumen y los avisos usan las reglas del backend ("1 hora" para llegar, "20 minutos" de tolerancia).
- Sin reglas del backend, los avisos no inventan valores.
- Confirmar crea la reserva con las fechas elegidas y la guarda en el teléfono con la etiqueta y la tolerancia. Como el backend ya consumió el bloqueo, salir después no lo libera.
- Rechazo de horario: vuelve al paso 2 con "No se puede reservar en este horario" y el mensaje de la base de datos, y el cajón sigue apartado (2 casos: fuera de horario y duración excedida).
- Bloqueo vencido: vuelve al paso 1 sin cajón, con "Se agotó el tiempo para reservar".

**Liberar el cajón (ViewModel)**
- Cancelar libera el cajón y sale.
- Regresar entre pasos conserva el cajón; salir desde el paso 1 lo libera.
- Salir de la pantalla libera el cajón.

**View (3)**
- Paso 1 como el mockup: "Paso 1 de 3", C1 seleccionado en amarillo (`#FFCE1B` sobre `#413817`), cajones no disponibles atenuados, C3 tocable y recuadro "Cajón C1".
- Pasos 2 y 3: hora de inicio, 11 opciones de fin, duración, resumen y botón "Confirmar reserva". Ante un rechazo de horario, vuelve al paso 2 con el banner y el error en el campo de fin.
- Con reserva activa se oculta el flujo y se muestra el aviso.

**Ocupación (1)**
- En el mapa, solo un cajón libre abre la reserva: tocar uno ocupado no hace nada.

### `test_mi_reserva.py` — 39 pruebas

**Carga y conexión**
- Muestra la reserva guardada y la confirma con el servidor: "¡Reserva confirmada!", horario "Hoy · 11:00 a 14:00", QR, "Conectado" y tiempo para llegar con la tolerancia.
- Sin internet sigue mostrando el QR guardado, con "Sin conexión".
- Sin copia local ni internet: pantalla "No se pudo conectar" con "Reintentar", que funciona al volver la red.
- Sin copia local, busca la reserva en el servidor y la guarda.
- Sin reserva vigente: pantalla correspondiente.
- La cuenta regresiva no se congela si el servidor tarda.
- Cerrar la pantalla durante una consulta no deja el ciclo de consultas corriendo.
- Consulta en cuanto MQTT reporta un cambio en su cajón (y no por cambios en otros cajones).

**Cuenta regresiva y fases**
- La cuenta regresiva avanza con el reloj ("47:30").
- Formato de la cuenta regresiva (6 casos: `00:00`, negativos en `00:00`, `00:59`, `60:00`, `1:00:01`, `2:05:00`).
- Al terminar la hora para llegar: "Vas con retraso", tolerancia restante (15:00) en naranja; todavía se puede cancelar.
- Sin tolerancia conocida muestra "--:--" y no inventa el tiempo.
- Al vencer la tolerancia: "Tu reserva expiró", el cajón quedó libre, botón "Ver cajones disponibles" y sin QR.
- Una llegada registrada en el último momento no se da por expirada: pasa a "en uso".
- Reserva expirada en el servidor: se muestra como expirada.

**Cancelar**
- Pide confirmación ("¿Cancelar tu reserva?") y, al aceptar: "Reserva cancelada", el QR ya no es válido y el cajón quedó libre.
- "Mantener reserva" cierra la confirmación.
- Si el estudiante ya llegó, el rechazo del backend sincroniza el estado a "en uso".
- Sin internet: "No se pudo conectar" y la reserva sigue activa.

**En uso, extender y salida**
- En uso como el mockup: sin QR (es de un solo uso), "Llegada registrada · En uso", tiempo restante "02:00:00", "Termina a las 14:00" y tabla con llegada, fin y duración.
- Extender actualiza la hora de fin ("Extendiste tu reserva hasta las 15:00.").
- Extensión rechazada: "No se pudo extender la reserva" con el motivo.
- Confirmar salida: "Salida confirmada" y el cajón queda libre.
- Horario terminado: tiempo en 00:00:00, "Tu horario terminó" y pide confirmar la salida o extender.
- Antes del aviso de fin no hay recuadro y la nota dice "Te avisaremos antes…".
- Dentro del aviso: "Tu reserva está por terminar", con salir o extender y el límite de 15 horas.
- Las reglas (`aviso_fin_min`, `duracion_max_h`) se leen una sola vez.
- Sin reglas, usa la marca del barrido (`notificado_fin_proximo`) y textos genéricos.
- Al extender desaparece el recuadro de fin y se muestra "Reserva extendida".

**View (5)**
- Fin próximo como el mockup: recuadro "Tu reserva está por terminar", "Extender 1 hora" y "Confirmar salida".
- Reserva confirmada como el mockup: banner, "Cajón C1", QR como imagen PNG, "Conectado", tiempo "60:00" y botón cancelar.
- En uso como el mockup: sin QR, tiempo restante, nota, tabla y "Confirmar salida".
- Retraso en naranja (`#F2A83B`) con "Tolerancia restante".
- Hoja de confirmación de cancelación y pantalla de resultado sin barra de título.

### `test_reservas_service.py` — 23 pruebas

**Edge Functions del estudiante (`reservas_service`, 21)**
- `bloquear-cajon`:
  - Envía el JWT del estudiante y la `apikey`, con el cuerpo `{"id_cajon": 3}`.
  - Lee la etiqueta, la hora de inicio y las reglas (60 min de llegada, 20 de tolerancia).
  - Si el backend no envía reglas, la app no las inventa.
- Un error de negocio conserva su código, su mensaje y su estado HTTP (p. ej. `CAJON_BLOQUEADO`, 409).
- Fallas del servidor (500 con error interno y 502 con HTML) se reportan como servicio no disponible (2 casos).
- JWT rechazado por el gateway: código `NO_AUTENTICADO`.
- Sin sesión no se hace la petición.
- Sin red: el error indica `sin_red`. Una función no desplegada (404) no se confunde con falta de red.
- `crear-reserva` envía las fechas y lee la reserva (estado `pendiente_llegada` y `codigo_qr`). La etiqueta se toma del cajón recalculado.
- `liberar-bloqueo` sin cajón libera todos los bloqueos del estudiante.
- `cancelar-reserva` y `confirmar-salida` envían el `id_reserva` (2 casos).
- `extender-reserva` devuelve la nueva hora de fin; si se rechaza, trae el motivo (`EXTENSION_NO_PERMITIDA`).
- Consultas de lectura:
  - La reserva vigente se busca en la tabla `reservas` con el JWT, filtrada por estudiante y por estados `pendiente_llegada` o `en_uso`.
  - Sin reserva vigente devuelve `None`.
  - Se obtiene una reserva por su id aunque ya haya terminado (p. ej. expirada).
  - Una consulta lenta se reporta como sin red.
- Las reglas se leen de la Edge Function `reglas-reserva`.

**Copia local (`almacen_reserva`, 2)**
- Guarda y lee la reserva del mismo estudiante; otra cuenta en el mismo teléfono no la ve; al borrar desaparece.
- Un archivo dañado se ignora.

### `test_inicio.py` — 7 pruebas de la tarjeta "Mi reserva"
- Sin reserva no hay tarjeta.
- Antes de la llegada: "Código QR y tiempo de tu reserva".
- En uso: insignia "En uso" y "Cajón C1 · termina a las 14:00"; al tocarla abre "Mi reserva".
- Sin red se muestra la copia local, sin borrarla.
- Si el servidor ya no tiene reserva vigente, se borra la copia local.
- El administrador no ve la tarjeta ni se consulta su reserva.
- La tarjeta se actualiza cuando MQTT reporta un cambio en el cajón de su reserva (y no en otros).

### `test_router.py` — 3 pruebas
- Tocar un cajón libre abre la reserva sobre Ocupación (`/inicio` → `/ocupacion` → `/reservar`) con ese cajón. Al salir, la pila vuelve a Ocupación y el cajón se libera.
- "Mi reserva" requiere sesión, se apila sobre Inicio y al salir detiene la cuenta regresiva y el ciclo de consultas.
- Al volver al menú desde "Mi reserva" se consulta de nuevo la reserva del estudiante.

### `test_router_notificaciones.py` — 5 pruebas
- Tocar un aviso lleva al estudiante a su reserva (4 casos: retraso de llegada, reserva expirada, fin próximo y fin alcanzado).
- Un aviso que llega con la app abierta actualiza "Mi reserva".

## Pruebas del backend (no ejecutadas en esta corrida)

`supabase/functions/_tests/operaciones.test.ts` tiene pruebas en Deno de las Edge Functions de reserva:
- Validación del JWT y que el id del usuario salga del token, nunca del cuerpo.
- Errores de negocio y reintento ante deadlock.
- Publicación MQTT y registro en Firestore solo cuando hay cambios.
- Reglas de `config_sistema`, liberar y extender.
- El barrido de reservas.

No se ejecutaron porque Deno no está instalado en este equipo (`deno test` desde `supabase/functions/`). Este documento solo cuenta las pruebas de la app (Python).
