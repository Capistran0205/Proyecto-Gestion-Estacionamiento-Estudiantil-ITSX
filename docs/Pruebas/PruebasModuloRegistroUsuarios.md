# Pruebas unitarias — Módulo de Registro de Usuarios

Sistema de Estacionamiento Estudiantil · App móvil (Flet + MVVM)
Fecha de ejecución: 2026-11-19 · Comando: `uv run pytest`

Todas las pruebas usan mocks: no se conectan a Supabase ni a EMQX reales.

## Resultado

| Archivo del registro | Capa | Archivo de prueba | Pruebas | Pasaron | Fallaron |
|---|---|---|---|---|---|
| `src/parking_app/viewmodels/registro_viewmodel.py` | ViewModel | `tests/test_registro_viewmodel.py` | 25 | 25 | 0 |
| `src/parking_app/views/registro_view.py` | View | `tests/test_registro_view.py` | 13 | 13 | 0 |
| `src/parking_app/core/validadores.py` | Core | `tests/test_validadores.py` | 27 | 27 | 0 |
| `src/parking_app/services/auth_service.py` (`registrar`) | Service | `tests/test_auth_service.py` (solo `test_registrar_*`) | 12 | 12 | 0 |
| `src/parking_app/services/emqx_admin_service.py` (`crear_credencial`) | Service | `tests/test_emqx_admin_service.py` | 3 | 3 | 0 |
| `src/parking_app/models/usuario.py` | Model | `tests/test_modelos.py` | 2 | 2 | 0 |
| `src/parking_app/router.py` (ruta `/registro`) | Navegación | `tests/test_router.py` | 1 | 1 | 0 |
| **Total** | | | **83** | **83** | **0** |

Suite completa del proyecto: 427 de 427 pruebas pasan.

## Flujo que cubren

1. La **View** captura los datos y filtra los caracteres no permitidos en nombres.
2. El **ViewModel** valida los campos con `core/validadores.py` y muestra los errores y los requisitos de contraseña en vivo.
3. `auth_service.registrar` envía el `sign_up` a Supabase Auth con los metadatos. Un trigger de `auth.users` crea la fila en `usuarios`.
4. `emqx_admin_service.crear_credencial` crea la cuenta MQTT con la misma contraseña. Le asigna un ACL de solo suscripción a `prueba1` y `reserva1/+`, y niega todo lo demás.
5. Si EMQX falla después de un registro exitoso en Supabase, se registra el error y el alta continúa.

## Detalle por archivo

### `test_registro_viewmodel.py` — 25 pruebas
- Sin errores antes del primer envío; los campos faltantes se listan como en el mockup.
- El apellido materno es opcional; con un solo faltante, el mensaje va en singular.
- Tras el primer envío, los errores se actualizan al escribir.
- Errores de formato: contraseña débil y contraseñas que no coinciden (2 casos).
- Números en nombre, apellido paterno o apellido materno no se registran (3 casos).
- Los nombres se envían sin espacios sobrantes; se rechaza un correo de otro dominio.
- Requisitos de contraseña en vivo (8 caracteres, mayúscula, minúscula, número y carácter especial).
- Registro exitoso: aprovisiona MQTT y pide confirmar el correo; sin confirmación usa el texto del mockup.
- Una falla de EMQX no bloquea el registro.
- Correo duplicado: muestra el aviso y se limpia al editar.
- Contraseña débil según Supabase: marca el campo hasta cambiarla.
- Correo rechazado por Supabase: marca el campo hasta editarlo; un rechazo sin campo muestra una alerta general.
- Mensajes de contraseña débil (3 casos) y errores del servicio (2 casos).

### `test_registro_view.py` — 13 pruebas
- Estado inicial de la pantalla; los campos faltantes se marcan con error.
- El filtro de nombre evalúa el texto completo (6 casos: acepta `Ma. Guadalupe D'Angelo-Núñez` y rechaza `A1`, `1` o `Ana@`).
- Los campos de nombre filtran números y muestran el error.
- Selección del medio de transporte y lista de requisitos de contraseña.
- Correo duplicado: muestra el banner "Este correo ya está registrado" y marca el campo de correo en naranja.
- Correo rechazado por Supabase: se marca en el campo.
- Pantalla de éxito.

### `test_validadores.py` — 27 pruebas
- Nombres válidos (8 casos: acentos, ñ, ü, guion, apóstrofo, punto, espacios sobrantes, vacío).
- Nombres con números o símbolos (6 casos) y nombre sin letras.
- Normalización de espacios en nombres.
- Correos institucionales válidos (3 casos: `@itsx.edu.mx`, `@xalapa.tecnm.mx`, mayúsculas y espacios).
- Correos inválidos (5 casos: vacío, `@gmail.com`, dominio con sufijo extra, subdominio, sin arroba).
- Contraseña válida, contraseña vacía y lista de requisitos faltantes.

### `test_auth_service.py` — 12 pruebas de `registrar`
- Envía los metadatos para el trigger y no inserta directo en la tabla.
- Sin confirmación de correo, cierra la sesión que abrió Supabase.
- Detecta el correo duplicado que Supabase oculta (usuario sin identidades).
- Traduce los errores: correo ya registrado, límite de correos, servicio no disponible (3 casos).
- Correo rechazado: indica el campo cuando aplica (2 casos).
- Una contraseña débil no se reporta como falla de conexión.
- Rechaza números en nombre y apellidos sin llamar a Supabase (3 casos).

### `test_emqx_admin_service.py` — 3 pruebas de `crear_credencial`
- Crea el usuario MQTT y su ACL de solo suscripción.
- Si el usuario ya existe (409), actualiza con PUT.
- Un error HTTP se reporta.

El archivo tiene otras 6 pruebas (de `actualizar_password` y de la migración de ACL). También pasan, pero no forman parte del registro.

### `test_modelos.py` — 2 pruebas de `Usuario`
- `to_row` deja los valores por defecto a la base de datos.
- `from_row` acepta columnas nulas.

### `test_router.py` — 1 prueba
- La pantalla de Registro se apila sobre Login (el botón de atrás regresa al login).

## Corrección aplicada (2026-11-19)

En la primera ejecución fallaron 2 pruebas (81 de 83). Se había agregado a `core/validadores.py` el requisito de 8 caracteres mínimos y no se actualizaron estas pruebas:

- `test_validadores.py::test_password_reporta_todos_los_faltantes`: ahora espera también "al menos 8 caracteres". La segunda verificación usaba `abc12345`, que sí trae número; se cambió a `abcdefgh` para comprobar el mensaje con tres faltantes.
- `test_registro_viewmodel.py::test_requisitos_de_password_en_vivo`: `abc1` (4 caracteres) ya no cumple la longitud; el primer valor esperado pasó de `True` a `False`.

También se corrigió el texto del requisito: decía "carácteres" y ahora dice "caracteres".
