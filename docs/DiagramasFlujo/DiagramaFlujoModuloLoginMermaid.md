# Diagrama de flujo — Módulo Login (Mermaid)

Proceso de inicio de sesión del estudiante (MVVM). Equivale a `DiagramaFlujoModuloLogin.puml`.

**Cómo leerlo:** cada cuadro pertenece a un actor o capa, que se distingue por su color. Los rombos son decisiones, los óvalos son inicio y fin, y los cuadros punteados son notas con el requisito que se cumple (RF, RNF o RN).

| Color | Actor o capa |
|---|---|
| Azul | Estudiante |
| Morado | Router |
| Verde | LoginView (View) |
| Naranja | LoginViewModel |
| Amarillo | AuthService |
| Verde azulado | Supabase |

```mermaid
flowchart TD
  classDef est fill:#E3F2FD,stroke:#455A64,color:#000
  classDef rou fill:#F3E5F5,stroke:#455A64,color:#000
  classDef vie fill:#E8F5E9,stroke:#455A64,color:#000
  classDef vm fill:#FFF3E0,stroke:#455A64,color:#000
  classDef aut fill:#FFFDE7,stroke:#455A64,color:#000
  classDef sup fill:#E0F2F1,stroke:#455A64,color:#000
  classDef nota fill:#FFF8E1,stroke:#F9A825,color:#000,stroke-dasharray:4 3

  n1(["Inicio"]):::est --> n2["Abre la aplicación"]:::est
  n2 --> n3["ir('login')<br/>_crear_login() crea LoginViewModel y LoginView"]:::rou
  n3 --> n4["montar(): se suscribe al ViewModel con add_listener()<br/>y pinta la pantalla con _render()"]:::vie
  n4 --> n5["Muestra los campos de correo y contraseña,<br/>el enlace de recuperación y el enlace de registro"]:::vie
  n5 -.- t1["RF-01: al abrir el sistema se muestra<br/>la pantalla de inicio de sesión"]:::nota
  n5 --> n6["Escribe su correo institucional y su contraseña"]:::est
  n6 --> n7["Cada CampoFormulario envía el cambio al ViewModel"]:::vie
  n7 --> n8["set_correo() y set_password() actualizan correo y password<br/>notify_listeners()"]:::vm
  n8 --> n9["_on_cambio() llama a _render()<br/>para refrescar campos, botón y banner"]:::vie
  n9 --> n10{"¿Qué elige el estudiante?"}:::est

  n10 -->|"Recuperar contraseña"| n11["_on_recuperar(e)"]:::vie
  n11 --> n12["ir_a_recuperar()<br/>invoca el callback _al_ir_a_recuperar"]:::vm
  n12 --> n13["Navega a la pantalla de recuperación de contraseña"]:::rou
  n13 -.- t2["RF-06"]:::nota
  n13 --> f1(["Fin"]):::est

  n10 -->|"Crear cuenta"| n14["_on_registro(e)"]:::vie
  n14 --> n15["ir_a_registro()<br/>invoca el callback _al_ir_a_registro"]:::vm
  n15 --> n16["Navega a la pantalla de registro"]:::rou
  n16 --> f2(["Fin"]):::est

  n10 -->|"Pulsa Iniciar sesión"| n17["_on_iniciar_sesion(e) recibe el clic del botón"]:::vie
  n17 --> n18["iniciar_sesion()<br/>normalizar_correo() normaliza el correo<br/>validar_correo_institucional() valida el dominio<br/>revisa que la contraseña no esté vacía"]:::vm
  n18 --> n19{"¿Datos válidos y sin bloqueo vigente?"}:::vm

  n19 -->|"No"| n20["Asigna error_correo o error_password<br/>o conserva la alerta de bloqueo activa"]:::vm
  n20 -.- t3["RNF-03: retroalimentación inmediata<br/>ante errores de validación"]:::nota
  n20 --> n60

  n19 -->|"Sí"| n21["cargando = verdadero<br/>notify_listeners()"]:::vm
  n21 -.- t4["RNF-01: el proceso debe responder<br/>en un máximo de 3 segundos"]:::nota
  n21 --> n22["iniciar_sesion(correo, contraseña)<br/>consulta ControlIntentos.segundos_restantes(correo)"]:::aut
  n22 --> n23{"¿Bloqueo vigente para el correo?"}:::aut

  n23 -->|"Sí"| n24["Lanza CuentaBloqueadaError<br/>con segundos_restantes"]:::aut
  n24 --> n50

  n23 -->|"No"| n25["sign_in_with_password(correo, contraseña)"]:::sup
  n25 --> n26{"¿Autenticación aceptada?"}:::sup

  n26 -->|"Sí"| n27["_obtener_usuario(id_usuario)"]:::aut
  n27 --> n28["Lee la fila de la tabla usuarios"]:::sup
  n28 --> n29["Construye el Usuario con from_row()"]:::aut
  n29 --> n30{"¿estado_cuenta activo?"}:::aut
  n30 -->|"No"| n31["Lanza CuentaInactivaError"]:::aut
  n31 --> n50
  n30 -->|"Sí"| n32["ControlIntentos.reiniciar(correo)<br/>limpia el contador de fallos"]:::aut
  n32 --> n33["_registrar_sesion(sesion)"]:::aut
  n33 --> n34["Inserta la fila en la tabla sesiones<br/>con token y estado ACTIVO"]:::sup
  n34 --> n35["Conserva en memoria _sesion, _usuario,<br/>_correo y _credenciales_mqtt"]:::aut
  n35 --> n36["Retorna la Sesion al ViewModel"]:::aut
  n36 --> n37["cargando = falso<br/>invoca el callback _al_iniciar_sesion"]:::vm
  n37 --> n38["ir(ruta de inicio)<br/>verifica con hay_sesion_activa si la ruta está protegida"]:::rou
  n38 --> n39["_mostrar(ruta) monta la vista de Inicio"]:::rou
  n39 -.- t5["RF-07"]:::nota
  n39 --> n40["Accede al menú principal del sistema"]:::est
  n40 --> f3(["Fin"]):::est

  n26 -->|"No"| n41{"¿Motivo del rechazo de Supabase?"}:::aut
  n41 -->|"Credenciales incorrectas"| n42["ControlIntentos.registrar_fallo(correo)"]:::aut
  n42 --> n43{"¿Se alcanzó el máximo de intentos?"}:::aut
  n43 -->|"Sí"| n44["Se bloquea el correo por 3 minutos<br/>Lanza CuentaBloqueadaError"]:::aut
  n44 -.- t6["RNF-08"]:::nota
  n43 -->|"No"| n45["Lanza CredencialesInvalidasError<br/>con intentos_restantes"]:::aut
  n41 -->|"Correo sin confirmar"| n46["Lanza CorreoNoConfirmadoError"]:::aut
  n41 -->|"Límite de solicitudes"| n47["Lanza DemasiadasSolicitudesError"]:::aut
  n41 -->|"Servicio no disponible"| n48["Lanza ServicioNoDisponibleError"]:::aut
  n44 --> n50
  n45 --> n50
  n46 --> n50
  n47 --> n50
  n48 --> n50

  n50["Captura la excepción AuthServiceError<br/>cargando = falso"]:::vm
  n50 --> n51{"¿Tipo de excepción?"}:::vm
  n51 -->|"CredencialesInvalidasError"| n52["Prepara _alerta_credenciales con los intentos restantes<br/>resaltar_campos = verdadero"]:::vm
  n52 -.- t7["RF-05 y RNF-07"]:::nota
  n51 -->|"CuentaBloqueadaError"| n53["_iniciar_cuenta_regresiva(segundos_restantes)<br/>_contar() descuenta segundos_bloqueo cada segundo"]:::vm
  n51 -->|"Otro AuthServiceError"| n54["Prepara _alerta_general para cuenta inactiva,<br/>correo sin confirmar, exceso de solicitudes<br/>o servicio no disponible"]:::vm
  n52 --> n60
  n53 --> n60
  n54 --> n60

  n60["notify_listeners() → _on_cambio() → _render()<br/>CampoFormulario.sincronizar() muestra los errores<br/>BannerAlerta.mostrar(alerta) muestra el aviso"]:::vie
  n60 --> n61["Visualiza el mensaje<br/>y puede reintentar cuando no haya bloqueo"]:::est
  n61 --> f4(["Fin"]):::est
```
