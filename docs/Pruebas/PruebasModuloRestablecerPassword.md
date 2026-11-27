# Pruebas unitarias — Módulo de Recuperar (restablecer) contraseña

Sistema de Estacionamiento Estudiantil · App móvil (Flet + MVVM)
Fecha de ejecución: 2026-11-19 · Comando: `uv run pytest`

Todas las pruebas usan mocks: no se conectan a Supabase ni a EMQX reales. La vigencia del código (10 minutos) se prueba con un reloj falso, sin esperar el tiempo real.

## Resultado

| Archivo del módulo | Capa | Archivo de prueba | Pruebas | Pasaron | Fallaron |
|---|---|---|---|---|---|
| `src/parking_app/viewmodels/recuperar_password_viewmodel.py` | ViewModel | `tests/test_recuperar_password_viewmodel.py` | 20 | 20 | 0 |
| `src/parking_app/views/recuperar_password_view.py` | View | `tests/test_recuperar_password_view.py` | 4 | 4 | 0 |
| `src/parking_app/services/auth_service.py` (`solicitar_restablecimiento`, `verificar_codigo_recuperacion`, `confirmar_nueva_password`) | Service | `tests/test_auth_service.py` (solo las de recuperación) | 7 | 7 | 0 |
| `src/parking_app/services/emqx_admin_service.py` (`crear_credencial`) | Service | `tests/test_emqx_admin_service.py` | 3 | 3 | 0 |
| `src/parking_app/core/validadores.py` (correo y requisitos de contraseña) | Core | `tests/test_validadores.py` (solo correo y contraseña) | 11 | 11 | 0 |
| **Total** | | | **45** | **45** | **0** |

Suite completa del proyecto: 427 de 427 pruebas pasan.

Las pruebas de `crear_credencial` y de los validadores son compartidas. También aparecen en `PruebasModuloRegistroUsuarios.md` y, las de correo, en `PruebasModuloLogin.md`.

## Flujo que cubren (3 pasos)

1. **Correo:** el ViewModel valida el correo institucional. `auth_service.solicitar_restablecimiento` pide a Supabase que envíe el código.
2. **Código:** el campo solo acepta dígitos y un temporizador muestra los 10 minutos de vigencia. Se puede pedir un código nuevo. `verificar_codigo_recuperacion` valida el código con `verify_otp` de tipo `recovery` y abre una sesión temporal.
3. **Nueva contraseña:** se validan los requisitos y que las dos contraseñas coincidan. `confirmar_nueva_password` actualiza Supabase Auth y cierra la sesión temporal. Después, `emqx_admin_service.crear_credencial` pone la misma contraseña en la cuenta MQTT.
   - Si EMQX falla, el cambio en Supabase se conserva y el flujo termina igual, como en el registro.

La vigencia real (10 minutos, un solo uso) la controla Supabase. El temporizador de la app solo informa al usuario.

## Detalle por archivo

### `test_recuperar_password_viewmodel.py` — 20 pruebas

**Paso 1 — Correo**
- Rechaza un correo que no es institucional sin llamar a Supabase.
- Envía el código, avanza al paso 2 y arranca el temporizador en 10:00 (a los 61 s marca 08:59).
- Límite de correos de Supabase: se queda en el paso 1 con la alerta "Espera un momento".

**Paso 2 — Código**
- El campo solo acepta dígitos (`"12a 3-4"` se convierte en `"1234"`).
- Código vacío: "Escribe el código de verificación" sin llamar al servicio.
- Código inválido: muestra el estado de error y lo limpia en cuanto el usuario escribe.
- Código vencido por tiempo: a los 600 s el temporizador marca 00:00 y se muestra el error.
- Reenviar: pide otro código, reinicia el temporizador a 10:00, limpia el error y el campo.
- Código correcto: avanza al paso 3.
- Falla de red al verificar: muestra "No se pudo conectar" sin marcar el código como inválido.

**Paso 3 — Nueva contraseña**
- Valida requisitos ("Tu contraseña no cumple los requisitos") y coincidencia ("Las contraseñas no coinciden") sin llamar a Supabase.
- Guardar: actualiza Supabase y la contraseña MQTT, termina el flujo y borra la contraseña de la memoria del ViewModel.
- Una falla de EMQX no impide terminar.
- Contraseña igual a la anterior: "Elige una contraseña distinta a la anterior"; permite reintentar y no toca EMQX.
- Contraseña débil según Supabase: muestra la razón y no toca EMQX.
- Sesión de recuperación expirada: regresa al paso 1 con "La verificación expiró".

**Navegación y limpieza**
- Regresar desde el paso 2 o 3 vuelve al paso 1. Desde el paso 3 también cierra la sesión temporal (2 casos).
- Regresar desde el paso 1 lleva al login.
- Al salir de la pantalla después de verificar el código, se cierra la sesión temporal.

### `test_recuperar_password_view.py` — 4 pruebas
- Paso 1: indicador "Paso 1 de 3", solo se ve el campo de correo y el botón dice "Enviar código".
- Paso 2: indicador "Paso 2 de 3", muestra el correo destino, el tiempo (10:00) y "reenviar"; el botón dice "Verificar código".
- Paso 2 con código inválido, como el mockup:
  - Aparece el banner "El código no es válido o ya venció" y el campo se marca en naranja con ícono.
  - Se ocultan el tiempo y "reenviar" y aparece la opción de pedir un código nuevo.
- Paso 3 y éxito: indicador "Paso 3 de 3", botón "Guardar contraseña". Al guardar se muestra la pantalla de éxito y se oculta el formulario.

### `test_auth_service.py` — 7 pruebas de recuperación
- Límite al solicitar el código (`reset_password_for_email`) → error de límite de correos.
- Verificar el código usa `verify_otp` con tipo `recovery` y normaliza el correo y el código (quita espacios y pasa el correo a minúsculas).
- Código vencido (`otp_expired`) → error de código inválido.
- Nueva contraseña exitosa: actualiza la contraseña y cierra la sesión de recuperación.
- Contraseña repetida (`same_password`): no cierra la sesión de recuperación, para poder reintentar.
- Contraseña débil: conserva las razones de Supabase y la sesión.
- Sin sesión de recuperación → error de sesión inexistente.

### `test_emqx_admin_service.py` — 3 pruebas de `crear_credencial`
- Crea el usuario MQTT y su ACL de solo suscripción.
- Si el usuario ya existe (409), actualiza la contraseña con PUT. Es el caso normal al restablecer, porque la cuenta MQTT ya existe desde el registro.
- Un error HTTP se reporta.

### `test_validadores.py` — 11 pruebas de correo y contraseña
- Correos institucionales válidos (3 casos) e inválidos (5 casos), usados en el paso 1.
- Contraseña válida, contraseña vacía y lista de requisitos faltantes (3 pruebas). El paso 3 usa `estado_requisitos_password`, que lee la misma tabla de requisitos que estas funciones.

## Observaciones

- **El router no tiene prueba propia de esta ruta.** Ninguna prueba de `test_router.py` comprueba que `/recuperar` se apile sobre el login. Ese comportamiento sí está cubierto para el registro.
- **`estado_requisitos_password` no tiene prueba directa.** Se cubre de forma indirecta con las pruebas de la tabla de requisitos.
- **`EmqxAdminService.actualizar_password` no se usa.** Tiene su prueba (`test_actualizar_password`), pero ninguna parte de la app la llama: la recuperación usa `crear_credencial`, que con el 409 hace el mismo PUT. Por eso no se contó aquí.
