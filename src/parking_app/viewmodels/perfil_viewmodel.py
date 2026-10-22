import asyncio
import logging

from parking_app.core.observable import Observable
from parking_app.core.validadores import normalizar_nombre, validar_nombre_apellido_persona
from parking_app.models.usuario import MedioTransporte, Rol
from parking_app.services.auth_service import (
    AuthService,
    DatosInvalidosError,
    MedioTransporteBloqueadoError,
    ServicioNoDisponibleError,
    SinSesionError,
)
from parking_app.viewmodels.alerta import Alerta
from parking_app.viewmodels.navegacion import Navegar, llamar

logger = logging.getLogger(__name__)

CAMPO_OBLIGATORIO = "Campo obligatorio"

ALERTA_CAMPOS = Alerta(
    "No se guardaron los cambios",
    "Corrige los campos marcados. Ningún dato se actualizará hasta que todos sean válidos.",
)
ALERTA_SIN_PERFIL = Alerta(
    "No se pudieron cargar tus datos",
    "Cierra sesión y vuelve a entrar para intentarlo de nuevo.",
)
TITULO_RESERVA_ACTIVA = "Tienes una reserva activa"
MENSAJE_EXITO = "Tus datos se actualizaron correctamente"

TEXTOS_ROL = {Rol.ESTUDIANTE: "Estudiante", Rol.ADMINISTRADOR: "Administrador"}


# Clase representativa de la pantalla "Mi perfil": edición de nombre, apellidos y
# medio de transporte (RF-01, RF-03, RF-07). El correo solo se muestra (RF-02).
class PerfilViewModel(Observable):
    def __init__(
        self,
        auth_service: AuthService,
        al_regresar: Navegar,
        al_ir_a_cambiar_password: Navegar,
        al_guardar: Navegar | None = None,
    ) -> None:
        super().__init__()
        self._auth = auth_service
        self._al_regresar = al_regresar
        self._al_ir_a_cambiar_password = al_ir_a_cambiar_password
        self._al_guardar = al_guardar

        usuario = auth_service.usuario_actual
        self.perfil_cargado = usuario is not None
        self.nombre = usuario.nombre if usuario else ""
        self.apellido_paterno = usuario.apellido_paterno if usuario else ""
        self.apellido_materno = (usuario.apellido_materno or "") if usuario else ""
        self.medio_transporte: MedioTransporte | None = usuario.medio_transporte if usuario else None

        self.errores: dict[str, str | None] = {}
        self.cargando = False
        self.guardado = False
        # Mensaje del trigger de RF-07 al intentar cambiar el medio con una reserva vigente.
        self.aviso_reserva: str | None = None
        self._alerta_general: Alerta | None = None
        self._errores_servidor: dict[str, str] = {}
        self._validar_en_vivo = False

    # --- Propiedades de presentación ---

    @property
    def correo(self) -> str:
        usuario = self._auth.usuario_actual
        return usuario.correo_institucional if usuario else (self._auth.correo_actual or "")

    @property
    def nombre_completo(self) -> str:
        """Nombre guardado (la tarjeta no cambia mientras se escribe)."""
        usuario = self._auth.usuario_actual
        return usuario.nombre_completo if usuario else "Estudiante"

    @property
    def iniciales(self) -> str:
        usuario = self._auth.usuario_actual
        return usuario.iniciales if usuario else (self.correo[:1] or "?").upper()

    @property
    def texto_rol(self) -> str:
        usuario = self._auth.usuario_actual
        return TEXTOS_ROL.get(usuario.rol, "Estudiante") if usuario else "Estudiante"

    def error(self, campo: str) -> str | None:
        return self.errores.get(campo)

    @property
    def alerta(self) -> Alerta | None:
        if not self.perfil_cargado:
            return ALERTA_SIN_PERFIL
        if self._alerta_general is not None:
            return self._alerta_general
        if any(self.errores.values()):
            return ALERTA_CAMPOS
        return None

    @property
    def alerta_reserva(self) -> Alerta | None:
        if self.aviso_reserva is None:
            return None
        return Alerta(TITULO_RESERVA_ACTIVA, self.aviso_reserva)

    @property
    def mensaje_exito(self) -> str | None:
        return MENSAJE_EXITO if self.guardado else None

    @property
    def puede_guardar(self) -> bool:
        return self.perfil_cargado and not self.cargando

    @property
    def hay_cambios(self) -> bool:
        usuario = self._auth.usuario_actual
        if usuario is None:
            return False
        return (
            normalizar_nombre(self.nombre) != usuario.nombre
            or normalizar_nombre(self.apellido_paterno) != usuario.apellido_paterno
            or (normalizar_nombre(self.apellido_materno) or None) != (usuario.apellido_materno or None)
            or self.medio_transporte != usuario.medio_transporte
        )

    # --- Entradas desde la View ---

    def set_nombre(self, valor: str) -> None:
        self.nombre = valor
        self._cambio("nombre")

    def set_apellido_paterno(self, valor: str) -> None:
        self.apellido_paterno = valor
        self._cambio("apellido_paterno")

    def set_apellido_materno(self, valor: str) -> None:
        self.apellido_materno = valor
        self._cambio("apellido_materno")

    def set_medio_transporte(self, valor: MedioTransporte) -> None:
        self.medio_transporte = valor
        self.aviso_reserva = None
        self._cambio("medio_transporte")

    # --- Comandos ---

    async def guardar(self) -> None:
        if not self.puede_guardar:
            return
        self._alerta_general = None
        self.guardado = False
        self._validar_en_vivo = True
        self._validar()
        if self.alerta is not None:
            self.notify_listeners()
            return
        if not self.hay_cambios:
            # Nada que enviar: los datos ya están como se ven.
            self.guardado = True
            self.notify_listeners()
            return

        self.cargando = True
        self.notify_listeners()
        try:
            usuario = await asyncio.to_thread(
                self._auth.actualizar_perfil,
                self.nombre,
                self.apellido_paterno,
                self.apellido_materno,
                self.medio_transporte,
            )
        except MedioTransporteBloqueadoError as e:
            self.aviso_reserva = str(e)
        except DatosInvalidosError as e:
            if e.campo is not None:
                self._errores_servidor[e.campo] = str(e)
                self._validar()
            else:
                logger.warning("La base rechazó los datos del perfil: %s", e)
                self._alerta_general = Alerta(
                    "No se guardaron los cambios",
                    "Revisa que tus datos solo tengan letras e intenta de nuevo.",
                )
        except SinSesionError:
            self._alerta_general = Alerta(
                "Tu sesión expiró", "Cierra sesión y vuelve a entrar para guardar tus cambios."
            )
        except ServicioNoDisponibleError:
            logger.exception("Fallo al guardar el perfil")
            self._alerta_general = Alerta(
                "No se pudieron guardar los cambios",
                "Revisa tu conexión a internet e intenta de nuevo.",
            )
        else:
            self.nombre = usuario.nombre
            self.apellido_paterno = usuario.apellido_paterno
            self.apellido_materno = usuario.apellido_materno or ""
            self.medio_transporte = usuario.medio_transporte
            self.guardado = True
            if self._al_guardar is not None:
                await llamar(self._al_guardar)
        finally:
            self.cargando = False
        self.notify_listeners()

    async def regresar(self) -> None:
        await llamar(self._al_regresar)

    async def ir_a_cambiar_password(self) -> None:
        await llamar(self._al_ir_a_cambiar_password)

    # --- Internos ---

    def _cambio(self, campo: str) -> None:
        self._errores_servidor.pop(campo, None)
        self.guardado = False
        self._alerta_general = None
        if self._validar_en_vivo:
            self._validar()
        self.notify_listeners()

    def _validar(self) -> None:
        def obligatorio(valor: str) -> str | None:
            return CAMPO_OBLIGATORIO if not valor.strip() else validar_nombre_apellido_persona(valor)

        errores: dict[str, str | None] = {
            "nombre": obligatorio(self.nombre),
            "apellido_paterno": obligatorio(self.apellido_paterno),
            "apellido_materno": validar_nombre_apellido_persona(self.apellido_materno),
            "medio_transporte": (
                "Selecciona tu medio de transporte" if self.medio_transporte is None else None
            ),
        }
        for campo, mensaje in self._errores_servidor.items():
            if errores.get(campo) is None:
                errores[campo] = mensaje
        self.errores = errores
