# Pruebas unitarias — Módulo de Modificación de usuario

Sistema de Estacionamiento Estudiantil · App móvil (Flet + MVVM) · Fase 2, Módulo A
Fecha de ejecución: 2026-11-19 · Comando: `uv run pytest`

El módulo tiene dos pantallas: **Perfil** (`/perfil`, datos del estudiante) y **Cambiar contraseña** (`/perfil/password`). Perfil se abre desde el menú sándwich y Cambiar contraseña, desde Perfil.

Todas las pruebas usan mocks: no se conectan a Supabase ni a EMQX reales. El bloqueo por intentos se prueba con un reloj falso.

## Resultado

| Archivo del módulo | Capa | Archivo de prueba | Pruebas | Pasaron | Fallaron |
|---|---|---|---|---|---|
| `src/parking_app/viewmodels/perfil_viewmodel.py` | ViewModel | `tests/test_perfil.py` | 7 | 7 | 0 |
| `src/parking_app/views/perfil_view.py` | View | `tests/test_perfil.py` | 4 | 4 | 0 |
| `src/parking_app/viewmodels/cambiar_password_viewmodel.py` | ViewModel | `tests/test_cambiar_password.py` | 7 | 7 | 0 |
| `src/parking_app/views/cambiar_password_view.py` | View | `tests/test_cambiar_password.py` | 1 | 1 | 0 |
| `src/parking_app/services/auth_service.py` (`actualizar_perfil`, `cambiar_password`) | Service | `tests/test_auth_service.py` (solo las de perfil y cambio de contraseña) | 11 | 11 | 0 |
| `src/parking_app/services/emqx_admin_service.py` (`crear_credencial`) | Service | `tests/test_emqx_admin_service.py` | 3 | 3 | 0 |
| `src/parking_app/core/validadores.py` (nombres y contraseña) | Core | `tests/test_validadores.py` (solo nombres y contraseña) | 19 | 19 | 0 |
| `src/parking_app/router.py` (rutas del perfil y efectos al guardar) | Navegación | `tests/test_router.py` | 2 | 2 | 0 |
| `src/parking_app/viewmodels/ocupacion_viewmodel.py` (reconexión MQTT) | ViewModel | `tests/test_ocupacion_viewmodel.py` | 1 | 1 | 0 |
| **Total** | | | **55** | **55** | **0** |

Suite completa del proyecto: 427 de 427 pruebas pasan.

Varias de estas pruebas también aparecen en otros documentos:
- `crear_credencial` y los validadores de nombres, en `PruebasModuloRegistroUsuarios.md`.
- Los validadores de contraseña, en el de registro y en `PruebasModuloRestablecerPassword.md`.
- La prueba de reconexión de `ocupacion_viewmodel`, en `PruebasModuloOcupacionCajones.md`.

## Flujo que cubren

### Perfil (modificación de datos)
1. El ViewModel carga los datos del estudiante en sesión. El correo se muestra en un campo de solo lectura (RF-02).
2. Se pueden editar nombre, apellidos (los mismos validadores del registro: sin números) y medio de transporte.
3. `auth_service.actualizar_perfil` valida otra vez y hace **un solo UPDATE** a `usuarios`, sin el correo (RNF-05). Si no hay cambios, no se hace ninguna petición.
4. Si el estudiante tiene una reserva vigente, el trigger de la base de datos rechaza el cambio de medio de transporte (RF-07) y la app muestra su mensaje.
5. Al guardar, el router actualiza el nombre que se ve en Inicio.

### Cambiar contraseña (RF-04, RNF-01)
1. Se valida en la app: la contraseña actual es obligatoria, la nueva debe cumplir los requisitos y ser distinta de la actual, y la confirmación debe coincidir.
2. `auth_service.cambiar_password` sigue este orden: **re-autentica** con la contraseña actual, **actualiza Supabase Auth** y **sincroniza EMQX** con `crear_credencial`.
3. Si EMQX falla, se **revierte** Supabase a la contraseña actual. Si tampoco se puede revertir, la nueva queda vigente y no se informa error.
4. Tres contraseñas actuales incorrectas bloquean el cambio por 3 minutos.
5. Al terminar, el router reconecta MQTT con la nueva contraseña.

El aviso por correo del cambio (RF-06) lo envía Supabase Auth; la app solo lo menciona en la pantalla de éxito.

## Detalle por archivo

### `test_perfil.py` — 11 pruebas

**ViewModel (7)**
- Carga los datos del estudiante: nombre, apellidos, medio de transporte, correo, iniciales ("AP"), nombre completo y rol ("Estudiante").
- Guardar envía un solo UPDATE con los cuatro campos editables, muestra "Tus datos se actualizaron correctamente" y avisa a Inicio. Al volver a editar, el aviso desaparece.
- Campos inválidos no se envían: nombre vacío ("Campo obligatorio") y apellido con número ("García2") muestran "No se guardaron los cambios". El error se limpia al corregir.
- Sin cambios no hay petición, pero se confirma igual.
- Con reserva activa: el rechazo del trigger se muestra junto al medio de transporte ("Tienes una reserva activa" y el mensaje de la base de datos), sin avisar a Inicio. Al regresar a la opción original, la alerta desaparece.
- Sin conexión: "No se pudieron guardar los cambios".
- Sin perfil cargado no se puede guardar: "No se pudieron cargar tus datos".

**View (4)**
- Vista inicial como el mockup: ruta `/perfil`, tarjeta con nombre completo e iniciales, campos llenos, correo de solo lectura y el medio de transporte actual seleccionado.
- Tras guardar aparece el aviso verde.
- Con reserva activa, la opción de transporte elegida se marca en naranja y aparece el banner "Tienes una reserva activa".
- Con errores, se muestran la alerta y el error en cada campo.

### `test_cambiar_password.py` — 8 pruebas

**ViewModel (7)**
- Cambio exitoso: llama a `cambiar_password` con la actual, la nueva y `crear_credencial` de EMQX. Termina el flujo, borra las tres contraseñas de la memoria y avisa al router.
- Validaciones locales sin llamar al servicio:
  - "Escribe tu contraseña actual", "Tu contraseña no cumple los requisitos" y "Las contraseñas no coinciden".
  - "La nueva contraseña debe ser distinta a la actual".
- Requisitos en vivo: con `abcdefgh` se cumplen longitud y minúscula, pero falta el número.
- Contraseña actual incorrecta como el mockup: error en el campo y alerta "No se pudo cambiar la contraseña". Se limpia al escribir otra.
- Bloqueo por intentos: "Demasiados intentos", con la espera de 3 minutos.
- Contraseña repetida según Supabase: "Elige una contraseña distinta a la actual".
- Falla de EMQX ya revertida: informa que la contraseña no cambió y no termina el flujo.

**View (1)**
- Formulario y éxito: ruta `/perfil/password`.
  - Con la contraseña actual incorrecta se muestran el banner y el error en el campo.
  - Al cambiar con éxito se oculta el formulario y aparece "Enviamos un aviso a {correo} como medida de seguridad."

### `test_auth_service.py` — 11 pruebas

**`actualizar_perfil` (5)**
- Hace un solo UPDATE sin el correo, filtrado por `id_usuario`, con los nombres normalizados (`"  Ana   Sofía "` → `"Ana Sofía"`, apellido materno vacío → `null`). También actualiza el usuario en sesión.
- Con reserva activa, convierte el error del trigger en `MedioTransporteBloqueadoError` con su mensaje y conserva el medio de transporte anterior.
- Valida antes de enviar: un apellido inválido no llega a la base de datos e indica el campo.
- Un UPDATE que no afecta ninguna fila se trata como error.
- Sin sesión, lanza `SinSesionError`.

**`cambiar_password` (6)**
- Re-autentica, actualiza Supabase y sincroniza EMQX en ese orden; las credenciales MQTT en memoria quedan con la nueva.
- Con la contraseña actual incorrecta no cambia nada (ni Supabase ni EMQX) e informa los intentos restantes.
- Bloquea después de tres intentos. Mientras dura el bloqueo, ni siquiera consulta a Supabase.
- Si EMQX falla, revierte Supabase con la contraseña actual y borra las credenciales MQTT.
- Si tampoco se puede revertir, la nueva queda vigente sin informar error, porque la cuenta ya cambió.
- Una contraseña débil según Supabase no llega a EMQX.

### `test_emqx_admin_service.py` — 3 pruebas de `crear_credencial`
- Crea el usuario MQTT y su ACL de solo suscripción.
- Si el usuario ya existe (409), actualiza la contraseña con PUT. Es el caso normal al cambiar la contraseña.
- Un error HTTP se reporta (y dispara la reversión en `cambiar_password`).

### `test_validadores.py` — 19 pruebas de nombres y contraseña
- Nombres válidos (8 casos), con números o símbolos (6 casos), sin letras (1) y normalización de espacios (1).
- Contraseña válida, contraseña vacía y lista de requisitos faltantes (3). La pantalla usa `estado_requisitos_password`, que lee la misma tabla de requisitos.

### `test_router.py` — 2 pruebas
- Perfil y Cambiar contraseña requieren sesión (sin ella, van al login) y se apilan sobre Inicio (`/inicio` → `/perfil` → `/perfil/password`). Al regresar, la pila vuelve a `/inicio` → `/perfil`.
- Al cambiar la contraseña se reconecta MQTT y al guardar el perfil se refresca Inicio.

### `test_ocupacion_viewmodel.py` — 1 prueba
- Después de cambiar la contraseña, la conexión MQTT se reabre con la nueva. Si no, el broker rechazaría la anterior.
