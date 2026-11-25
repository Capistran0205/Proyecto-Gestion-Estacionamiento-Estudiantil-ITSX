# Guía: pasar los diagramas de flujo Mermaid a draw.io

Esta guía es para quien reciba los archivos `DiagramaFlujo...Mermaid.md` y los quiera editar en draw.io (diagrams.net).

## Archivos

| Archivo | Contenido |
|---|---|
| `DiagramaFlujoModuloLoginMermaid.md` | Inicio de sesión |
| `DiagramaFlujoModuloRegistroMermaid.md` | Registro de usuarios |
| `DiagramaFlujoModuloRestablecerPasswordMermaid.md` | Restablecer contraseña (3 pasos) |
| `DiagramaFlujoModuloOcupacionCajonesMermaid.md` | Visualización de ocupación (MQTT en tiempo real) |
| `DiagramaFlujoModuloModificacionUsuarioMermaid.md` | Perfil y cambio de contraseña |
| `DiagramaFlujoModuloReservaCajonMermaid.md` | Reserva de cajón, flujo del estudiante |
| `DiagramaFlujoModuloReservaCajonAdminMermaid.md` | Reserva de cajón, flujo del administrador |
| `DiagramaFlujoFirmwareESP32Mermaid.md` | Firmware del ESP32 (`main.py`) |

Todos usan la misma convención: cada cuadro se colorea según el actor o la capa a la que pertenece (la leyenda está al inicio de cada archivo), los rombos son decisiones, los óvalos son inicio y fin, y los cuadros punteados amarillos son notas con el requisito (RF, RNF o RN).

## Importar en draw.io

1. Abre el archivo `.md` y copia **solo el código** que está entre las líneas ` ```mermaid ` y ` ``` `, sin incluir esas dos líneas.
2. En draw.io entra a **Arrange → Insert → Advanced → Mermaid** (el nombre del menú puede variar un poco según la versión).
3. Pega el código y elige la opción que genera un diagrama **editable** (formas de draw.io), no una imagen. Pulsa **Insert**.
4. Revisa el resultado. Es normal reordenar a mano, y los diagramas grandes (Reserva de cajón y Restablecer contraseña) conviene dividirlos en páginas.

Alternativa si el paso 3 falla o los colores no se conservan: pega el código en <https://mermaid.live>, exporta como SVG y arrastra el SVG a draw.io. Quedará como imagen vectorial, no editable, pero sirve de guía para redibujar.

## Si los colores no se conservan

Los colores de cada capa son estos, para volver a aplicarlos como estilo en draw.io:

| Actor o capa | Relleno | Borde |
|---|---|---|
| Estudiante | `#E3F2FD` | `#455A64` |
| Router | `#F3E5F5` | `#455A64` |
| View | `#E8F5E9` | `#455A64` |
| ViewModel | `#FFF3E0` | `#455A64` |
| AuthService o servicio del módulo | `#FFFDE7` | `#455A64` |
| Supabase o MqttService | `#E0F2F1` | `#455A64` |
| ESP32, EMQX o backend | `#ECEFF1` | `#455A64` |
| Administrador | `#FCE4EC` | `#455A64` |
| Nota (RF, RNF, RN) | `#FFF8E1` | `#F9A825`, punteado |

## Consejos para el rediseño

- **Carriles (swimlanes):** el diagrama original en PlantUML usa un carril por actor. En Mermaid se sustituyeron por colores. Si el equipo prefiere carriles, en draw.io se pueden crear con la forma *Swimlane* o *Pool* y arrastrar adentro los cuadros según su color.
- **Ciclos:** las flechas que vuelven hacia atrás representan repeticiones, por ejemplo cada paso del restablecimiento o el ciclo de tiempo real de ocupación.
- **Notas:** están unidas con una línea punteada al cuadro que cumple el requisito. Pueden convertirse en formas *Note* de draw.io.
