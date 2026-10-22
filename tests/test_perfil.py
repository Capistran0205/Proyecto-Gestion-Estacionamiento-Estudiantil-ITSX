"""Módulo A: Mi perfil (ViewModel + View)."""

import asyncio
from unittest.mock import MagicMock

from parking_app.core import theme
from parking_app.models.usuario import MedioTransporte, Usuario
from parking_app.services.auth_service import (
    MedioTransporteBloqueadoError,
    ServicioNoDisponibleError,
)
from parking_app.viewmodels.perfil_viewmodel import PerfilViewModel
from parking_app.views.perfil_view import PerfilView

MENSAJE_TRIGGER = "No puedes cambiar tu medio de transporte mientras tengas una reserva activa."


def _usuario(**cambios):
    datos = dict(
        id_usuario="uid", nombre="Ana Sofía", apellido_paterno="Pérez", apellido_materno="López",
        correo_institucional="237o00526@itsx.edu.mx", medio_transporte=MedioTransporte.VEHICULO,
    )
    return Usuario(**{**datos, **cambios})


def _vm(usuario=None):
    auth = MagicMock()
    auth.usuario_actual = usuario if usuario is not None else _usuario()

    def actualizar(nombre, paterno, materno, medio):
        auth.usuario_actual = _usuario(
            nombre=nombre.strip(), apellido_paterno=paterno, apellido_materno=materno or None,
            medio_transporte=medio,
        )
        return auth.usuario_actual

    auth.actualizar_perfil.side_effect = actualizar
    al_guardar = MagicMock()
    vm = PerfilViewModel(auth, MagicMock(), MagicMock(), al_guardar=al_guardar)
    return vm, auth, al_guardar


def test_carga_los_datos_del_estudiante():
    vm, _, _ = _vm()
    assert (vm.nombre, vm.apellido_paterno, vm.apellido_materno) == ("Ana Sofía", "Pérez", "López")
    assert vm.medio_transporte is MedioTransporte.VEHICULO
    assert vm.correo == "237o00526@itsx.edu.mx"
    assert (vm.iniciales, vm.nombre_completo, vm.texto_rol) == ("AP", "Ana Sofía Pérez López", "Estudiante")
    assert vm.alerta is None and vm.mensaje_exito is None


def test_guardar_envia_un_solo_update_y_avisa_al_inicio():
    vm, auth, al_guardar = _vm()
    vm.set_nombre("Ana")
    vm.set_medio_transporte(MedioTransporte.MOTOCICLETA)

    asyncio.run(vm.guardar())

    auth.actualizar_perfil.assert_called_once_with("Ana", "Pérez", "López", MedioTransporte.MOTOCICLETA)
    assert vm.mensaje_exito == "Tus datos se actualizaron correctamente"
    assert vm.nombre_completo == "Ana Pérez López"
    al_guardar.assert_called_once()
    # Al volver a editar, el aviso de éxito desaparece.
    vm.set_nombre("Ana María")
    assert vm.mensaje_exito is None


def test_campos_invalidos_no_se_envian():
    vm, auth, _ = _vm()
    vm.set_nombre("   ")
    vm.set_apellido_paterno("García2")

    asyncio.run(vm.guardar())

    auth.actualizar_perfil.assert_not_called()
    assert vm.alerta.titulo == "No se guardaron los cambios"
    assert vm.error("nombre") == "Campo obligatorio"
    assert vm.error("apellido_paterno") is not None
    # Tras el primer intento, se valida al escribir.
    vm.set_nombre("Ana")
    assert vm.error("nombre") is None


def test_sin_cambios_no_hay_peticion():
    vm, auth, _ = _vm()
    asyncio.run(vm.guardar())
    auth.actualizar_perfil.assert_not_called()
    assert vm.mensaje_exito is not None


def test_reserva_activa_muestra_el_mensaje_del_trigger_junto_al_medio():
    vm, auth, al_guardar = _vm()
    auth.actualizar_perfil.side_effect = MedioTransporteBloqueadoError(MENSAJE_TRIGGER)
    vm.set_medio_transporte(MedioTransporte.MOTOCICLETA)

    asyncio.run(vm.guardar())

    assert vm.alerta_reserva.titulo == "Tienes una reserva activa"
    assert vm.alerta_reserva.detalle == MENSAJE_TRIGGER
    assert vm.mensaje_exito is None
    al_guardar.assert_not_called()

    vm.set_medio_transporte(MedioTransporte.VEHICULO)
    assert vm.alerta_reserva is None


def test_sin_conexion():
    vm, auth, _ = _vm()
    auth.actualizar_perfil.side_effect = ServicioNoDisponibleError("x")
    vm.set_nombre("Ana")
    asyncio.run(vm.guardar())
    assert vm.alerta.titulo == "No se pudieron guardar los cambios"
    assert not vm.cargando


def test_sin_perfil_cargado_no_se_puede_guardar():
    auth = MagicMock()
    auth.usuario_actual = None
    auth.correo_actual = "237o00526@itsx.edu.mx"
    vm = PerfilViewModel(auth, MagicMock(), MagicMock())
    assert not vm.puede_guardar
    assert vm.alerta.titulo == "No se pudieron cargar tus datos"


# --- View ---

def _vista():
    vm, auth, _ = _vm()
    vista = PerfilView(vm)
    vista.montar()
    return vista, vm, auth


def test_vista_inicial_como_el_mockup():
    vista, _, _ = _vista()
    assert vista.view.route == "/perfil"
    assert vista._nombre_tarjeta.value == "Ana Sofía Pérez López"
    assert vista._iniciales.value == "AP"
    assert vista._nombre.campo.value == "Ana Sofía"
    assert vista._correo.campo.value == "237o00526@itsx.edu.mx"
    assert vista._correo.campo.read_only
    assert vista._opciones_transporte[MedioTransporte.VEHICULO].seleccionada
    assert vista._banner.titulo is None and vista._banner_exito.texto is None


def test_vista_tras_guardar_muestra_el_aviso_verde():
    vista, vm, _ = _vista()
    vm.set_apellido_materno("Ruiz")
    asyncio.run(vm.guardar())
    assert vista._banner_exito.texto == "Tus datos se actualizaron correctamente"


def test_vista_con_reserva_activa_marca_la_opcion_en_naranja():
    vista, vm, auth = _vista()
    auth.actualizar_perfil.side_effect = MedioTransporteBloqueadoError(MENSAJE_TRIGGER)
    vm.set_medio_transporte(MedioTransporte.MOTOCICLETA)
    asyncio.run(vm.guardar())

    moto = vista._opciones_transporte[MedioTransporte.MOTOCICLETA]
    assert moto.control.bgcolor == theme.ALERTA_FONDO
    assert vista._banner_reserva.titulo == "Tienes una reserva activa"


def test_vista_con_errores_muestra_la_alerta_y_los_campos():
    vista, vm, _ = _vista()
    vm.set_nombre("")
    asyncio.run(vm.guardar())
    assert vista._banner.titulo == "No se guardaron los cambios"
    assert vista._nombre.error.texto == "Campo obligatorio"
