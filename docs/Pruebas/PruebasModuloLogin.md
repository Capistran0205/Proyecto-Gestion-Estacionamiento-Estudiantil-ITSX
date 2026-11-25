# Pruebas unitarias — Módulo de Login

Sistema de Estacionamiento Estudiantil · App móvil (Flet + MVVM)
Fecha de ejecución: 2026-11-19 · Comando: `uv run pytest`

Todas las pruebas usan mocks: no se conectan a Supabase ni a EMQX reales. El bloqueo por tiempo se prueba con un reloj falso, sin esperar los 3 minutos reales.

## Resultado

| Archivo del login | Capa | Archivo de prueba | Pruebas | Pasaron | Fallaron |
|---|---|---|---|---|---|
| `src/parking_app/viewmodels/login_viewmodel.py` | ViewModel | `tests/test_login_viewmodel.py` | 11 | 11 | 0 |
| `src/parking_app/views/login_view.py` | View | `tests/test_login_view.py` | 4 | 4 | 0 |
| `src/parking_app/services/auth_service.py` (`iniciar_sesion`, `cerrar_sesion`, `ControlIntentos`) | Service | `tests/test_auth_service.py` (solo las de login y sesión) | 18 | 18 | 0 |
| `src/parking_app/core/validadores.py` (`validar_correo_institucional`) | Core | `tests/test_validadores.py` (solo las de correo) | 8 | 8 | 0 |
| `src/parking_app/router.py` (guardia de sesión) | Navegación | `tests/test_router.py` | 2 | 2 | 0 |
| **Total** | | | **43** | **43** | **0** |

Suite completa del proyecto: 427 de 427 pruebas pasan.

Las 8 pruebas de correo institucional también aparecen en `PruebasModuloRegistroUsuarios.md`, porque los dos módulos usan el mismo validador.

## Flujo que cubren

1. La **View** captura el correo y la contraseña y muestra el texto de ayuda con los dominios permitidos.
2. El **ViewModel** valida los campos antes de llamar al servicio y traduce cada error a un banner.
3. `auth_service.iniciar_sesion` autentica con Supabase Auth y guarda la sesión y las credenciales MQTT en memoria. Después registra la sesión en la tabla `sesiones` con una huella del token.
4. `ControlIntentos` bloquea el correo por 3 minutos después de 3 intentos fallidos. Solo cuentan las credenciales inválidas: los fallos de red o de límite de peticiones no cuentan.
5. El **router** impide entrar a pantallas protegidas sin sesión y regresar al login con una sesión abierta.

## Detalle por archivo

### `test_login_viewmodel.py` — 11 pruebas
- Valida los campos antes de llamar al servicio: con un correo de otro dominio (`@gmail.com`) y sin contraseña ("Ingresa tu contraseña") no se llama a `iniciar_sesion` ni se navega.
- Login exitoso: navega a Inicio y borra la contraseña de la memoria del ViewModel.
- Credenciales inválidas: muestra la alerta del mockup ("Correo o contraseña incorrectos") con los intentos restantes, resalta los campos y conserva la contraseña escrita.
- El último intento se anuncia en singular ("Te queda 1 intento.").
- Bloqueo: deshabilita el botón y muestra "Acceso bloqueado temporalmente" con la cuenta regresiva (3:00).
- Cuenta inactiva: muestra "Cuenta inactiva" sin resaltar los campos.
- Falla de red: muestra "No se pudo conectar".
- Datos rechazados por formato: muestra "Datos no válidos"; no se toma como falla de conexión ni bloquea.
- Límite de peticiones: muestra "Demasiados intentos" y "Espera un momento…" sin bloquear la cuenta.
- Un nuevo intento limpia la alerta anterior.
- Cada cambio de estado notifica a la vista (patrón observer).

### `test_login_view.py` — 4 pruebas
- Estado inicial como el mockup: ruta `/login`, banner oculto, texto de ayuda "Usa tu correo @itsx.edu.mx o @xalapa.tecnm.mx", contraseña oculta y botón habilitado.
- Credenciales inválidas: aparece el banner, los dos campos se marcan en naranja y se conserva lo escrito.
- Un error de validación del correo reemplaza el texto de ayuda y marca el campo.
- Al desmontar, la vista deja de escuchar al ViewModel.

### `test_auth_service.py` — 18 pruebas de login y sesión
- Login exitoso: guarda la sesión y las credenciales MQTT.
- Descartar la contraseña MQTT conserva el correo hasta cerrar la sesión.
- Bloqueo tras 3 fallos y desbloqueo exacto a los 3 minutos: a los 179 s sigue bloqueado y ni siquiera llama a Supabase; a los 180 s se desbloquea.
- Una falla de red no cuenta como intento.
- Solo `invalid_credentials` cuenta como intento. Los demás errores se traducen sin bloquear (6 casos):
  - `email_address_invalid` y `validation_failed` → datos inválidos.
  - `user_banned` → cuenta inactiva.
  - `captcha_failed`, `email_provider_disabled` y un 401 sin código → servicio no disponible.
- El límite de peticiones (429, con y sin código) no cuenta como intento (2 casos).
- Un error de configuración deja su código en el log (por ejemplo `captcha_failed`).
- Un error desconocido deja la causa real en el log.
- Una cuenta inactiva no inicia sesión.
- El login registra la sesión con una huella del token (no guarda el token completo).
- Si falla el registro de la sesión en la tabla, el login sigue adelante.
- Cerrar sesión cierra el registro en la tabla antes del `sign_out`.

### `test_validadores.py` — 8 pruebas de correo
- Correos institucionales válidos (3 casos: `@itsx.edu.mx`, `@xalapa.tecnm.mx`, con mayúsculas y espacios alrededor).
- Correos inválidos (5 casos: vacío, `@gmail.com`, dominio con sufijo extra, subdominio, sin arroba).

### `test_router.py` — 2 pruebas
- Sin sesión activa no se llega a la pantalla de ocupación: el router redirige al login y no abre la conexión MQTT.
- Con sesión activa no se vuelve al login: el router redirige a Inicio.
