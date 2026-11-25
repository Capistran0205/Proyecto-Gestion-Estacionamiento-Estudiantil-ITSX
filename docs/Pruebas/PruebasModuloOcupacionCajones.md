# Pruebas unitarias — Módulo de Ocupación de cajones

Sistema de Estacionamiento Estudiantil · App móvil (Flet + MVVM)
Fecha de ejecución: 2026-11-19 · Comando: `uv run pytest`

Todas las pruebas usan mocks: no se conectan a Supabase, al broker EMQX ni a la ESP32 reales. El timeout de los nodos se prueba con un reloj falso, sin esperar el tiempo real. Los mensajes de paho se simulan desde otro hilo para comprobar que llegan bien al loop de la app.

## Resultado

| Archivo del módulo | Capa | Archivo de prueba | Pruebas | Pasaron | Fallaron |
|---|---|---|---|---|---|
| `src/parking_app/viewmodels/ocupacion_viewmodel.py` | ViewModel | `tests/test_ocupacion_viewmodel.py` | 23 | 23 | 0 |
| `src/parking_app/views/ocupacion_view.py` + `components/tarjeta_cajon.py`, `pildora_conexion.py` | View | `tests/test_ocupacion_view.py` | 3 | 3 | 0 |
| `src/parking_app/services/mqtt_service.py` | Service | `tests/test_mqtt_service.py` | 8 | 8 | 0 |
| `src/parking_app/services/cajones_service.py` | Service | `tests/test_cajones_service.py` | 3 | 3 | 0 |
| `src/parking_app/models/evento_ocupacion.py`, `cajon_estacionamiento.py` (`estado_efectivo`), `core/theme.py` (colores) | Model / Core | `tests/test_evento_ocupacion.py` | 24 | 24 | 0 |
| `src/parking_app/models/cajon_estacionamiento.py` | Model | `tests/test_modelos.py` (solo las de cajón) | 2 | 2 | 0 |
| `src/parking_app/router.py` (conexión compartida y guardia de sesión) | Navegación | `tests/test_router.py` | 2 | 2 | 0 |
| **Total** | | | **65** | **65** | **0** |

Suite completa del proyecto: 427 de 427 pruebas pasan.

La prueba del router `test_sin_sesion_no_se_llega_a_ocupacion` también aparece en `PruebasModuloLogin.md`.

## Flujo que cubren

1. **Snapshot inicial:** `cajones_service.obtener_estado_actual()` lee la tabla `cajones` y devuelve siempre los 4 cajones (C1–C4) en orden.
2. **Conexión MQTT:** `mqtt_service` se conecta con el correo y la contraseña del usuario. Usa TLS en el puerto 8883 y se suscribe a dos tópicos:
   - `infraestructura/pruebaiot/prueba1`: el sensor de la ESP32.
   - `infraestructura/pruebaiot/reserva1/+`: el estado que publica el backend.
3. **Mensajes:** cada payload se convierte en `EventoOcupacion` (sensor) o `EventoSistema` (backend). `id_modulo` se traduce a la etiqueta ("C" + id). Los mensajes inválidos se descartan sin afectar a los demás cajones.
4. **Hilos:** paho entrega los mensajes en su propio hilo; el ViewModel los pasa al loop de la app antes de notificar a la vista.
5. **Estado efectivo:** el ViewModel combina sensor y sistema con la misma regla que el backend: no conectado → ocupado → reservado → bloqueado → libre. Solo un cajón `libre` se puede seleccionar para reservar.
6. **Timeout:** un nodo que deja de reportar durante el tiempo configurado (60 s en las pruebas) pasa a "no conectado".
7. **Router:** Inicio y Ocupación comparten una sola conexión MQTT, que se cierra al salir de la sesión.

## Detalle por archivo

### `test_ocupacion_viewmodel.py` — 23 pruebas

**Carga y conexión**
- Estado inicial antes de cargar: los 4 cajones "no conectado", "0 de 4 cajones libres", "Conectando…" y "Cargando estado del estacionamiento…".
- Snapshot y conexión con las credenciales del usuario: se pinta el estado de la base de datos ("2 de 4 cajones libres") y al detener se desconecta.
- Los eventos que llegan desde el hilo de paho llegan al loop, la vista se entera y la píldora dice "En vivo".
- Un evento que llega mientras la consulta a Supabase sigue en curso no se pierde cuando termina el snapshot.
- Si falla el snapshot, la vista no se bloquea: muestra "Esperando datos de los sensores…" y conecta MQTT de todos modos.
- Sin credenciales MQTT: no intenta conectar y muestra "Sin acceso" y "No se pudo acceder al servidor de sensores".
- Texto de última actualización: "hace 12 segundos", "hace 1 minuto", "hace más de una hora".
- Texto de cajones libres como el mockup ("1 de 4 cajones libres").

**Timeout de nodos**
- Un nodo sin reportar pasa a "no conectado". Con timeout de 60 s, C1, C3 y C4 (61 s sin datos) cambian y C2 (31 s) sigue libre.
- Sin conexión al broker no se aplica el timeout: los cajones conservan su último estado, aunque pasen 600 s.
- Un nodo caído se ve "no conectado" aunque el cajón esté reservado.

**Credenciales y reconexión**
- Al conectar se descarta la contraseña de la memoria y no se llama a EMQX.
- Si el broker rechaza la credencial, se vuelve a sincronizar con EMQX y se reconecta. Si lo logra, queda "En vivo" y se borra la contraseña.
- Si el broker la rechaza otra vez, no hay un tercer intento: muestra "Sin acceso".
- Si EMQX falla al resincronizar, muestra "Sin acceso" y no reconecta.
- Un rechazo después de haber estado conectado no resincroniza con la contraseña vieja.
- Detener la vista cancela la resincronización en curso.
- Tras cambiar la contraseña en el perfil, se reconecta con la nueva.

**Estado efectivo (sensor + sistema)**
- Combina sensor y sistema: reservado, bloqueado, ocupado (la lectura física manda) y libre. Solo el libre es seleccionable. Al recibir "liberado", el cajón vuelve a libre.
- Los bloqueados cuentan como no disponibles: 3 libres, 1 bloqueado, 25 % ocupado.
- El snapshot reconstruye sensor y sistema a partir del estado guardado. En un cajón reservado: si llega un vehículo se ve ocupado, y al irse vuelve a reservado, porque la reserva no se canceló.
- Los mensajes del sistema (`reserva1/+`) también llegan desde el hilo de paho.
- Una lectura de sensor con un estado que solo puede venir del sistema (p. ej. "reservado") se ignora.

### `test_ocupacion_view.py` — 3 pruebas
- Estado inicial: ruta `/ocupacion`, "0 de 4 cajones libres", píldora "Conectando…" y todas las tarjetas en gris (`#9ca3af`).
- Los eventos colorean cada cajón como el mockup:
  - Libre, ocupado, reservado y no conectado, con su color de acento y su texto.
  - Al bloquearse, C1 cambia a "Bloqueado" con `#FFCE1B`.
  - La píldora cambia a "En vivo".
- Al desmontar la vista no se cierra la conexión MQTT, porque la comparte con Inicio.

### `test_mqtt_service.py` — 8 pruebas
- Conecta con TLS y las credenciales del usuario (puerto 8883) y arranca el loop de paho.
- En el puerto 1883 se conecta sin TLS.
- Al conectar se suscribe a `prueba1` y a `reserva1/+` con QoS 1 y reporta "conectado".
- Si el broker rechaza las credenciales, se desconecta y deja de reintentar.
- Si se pierde la conexión, pasa a "reconectando".
- Mensajes válidos e inválidos: de tres payloads (uno válido, `basura` y uno con `id_modulo` 9 sin estado), solo el válido llega como evento de C3 "ocupado".
- Los mensajes de `reserva1/{n}` van al callback del sistema (C2 "reservado").
- Desconectar detiene el cliente (`disconnect` y `loop_stop`).

### `test_cajones_service.py` — 3 pruebas
- Consulta la tabla `cajones` y devuelve los 4 cajones en orden C1–C4.
- Una fila inválida no rompe el resto: siempre regresa 4 cajones.
- Un error de red se reporta como `CajonesNoDisponiblesError`.

### `test_evento_ocupacion.py` — 24 pruebas
- Un payload válido traduce `id_modulo` a la etiqueta (2 → "C2") y genera `origen_evento` y `marca_tiempo` al recibirlo.
- Payloads inválidos que se rechazan (10 casos):
  - Texto que no es JSON, una lista, bytes que no son UTF-8.
  - Sin `id_modulo`, `id_modulo` fuera de rango (5), como texto (`"1"`) o booleano.
  - Un estado desconocido (`averiado`), y `reservado` o `bloqueado` llegando por el tópico del sensor.
- Todos los estados tienen color en el tema; bloqueado usa `#FFCE1B`.
- Un payload del sistema se interpreta bien (C3 "liberado").
- Regla de estado efectivo (6 casos):
  - no conectado + reservado → no conectado.
  - ocupado + reservado → ocupado; ocupado + bloqueado → ocupado.
  - libre + reservado → reservado; libre + bloqueado → bloqueado.
  - libre + liberado → libre.
- El snapshot se reconstruye sin perder el estado, uno por cada estado posible (5 casos).

### `test_modelos.py` — 2 pruebas de cajón
- `EstadoCajon` acepta el formato de MQTT (`"no conectado"`) y el de la base de datos (`"no_conectado"`).
- Un cajón se crea correctamente a partir de una fila de la base de datos.

### `test_router.py` — 2 pruebas
- Sin sesión activa no se llega a la pantalla de ocupación y no se abre la conexión MQTT.
- Una sola conexión MQTT para Inicio y Ocupación aunque se navegue varias veces entre ellas; al ir al login se desconecta y se libera el ViewModel.
