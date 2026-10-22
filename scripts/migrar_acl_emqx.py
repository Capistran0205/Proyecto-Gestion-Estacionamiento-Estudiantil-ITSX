"""Da acceso a `reserva1/+` a los usuarios MQTT que ya existían en EMQX (Fase 2).

Por defecto solo muestra qué cambiaría; con --aplicar escribe en EMQX.

    uv run python scripts/migrar_acl_emqx.py
    uv run python scripts/migrar_acl_emqx.py --esp32 <usuario_esp32>
    uv run python scripts/migrar_acl_emqx.py --esp32 <usuario_esp32> --aplicar

Lee EMQX_API_URL, EMQX_API_KEY, EMQX_API_SECRET y MQTT_TOPIC_SISTEMA_BASE del .env.
"""

import argparse
import sys

from parking_app.core.config import get_settings
from parking_app.services.emqx_admin_service import EmqxAdminService, planear_migracion_acl


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # consola de Windows (cp1252)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--esp32",
        action="append",
        default=[],
        metavar="USUARIO",
        help="usuario MQTT de la ESP32 (se le antepone el permiso; se puede repetir)",
    )
    parser.add_argument("--aplicar", action="store_true", help="escribir los cambios en EMQX")
    args = parser.parse_args()

    servicio = EmqxAdminService()
    topico_sistema = f"{get_settings().mqtt_topic_sistema_base}/+"
    acl = list(servicio.listar_acl())
    cambios = planear_migracion_acl(acl, servicio.reglas_estudiante(), topico_sistema, args.esp32)

    faltantes = set(args.esp32) - {e.get("username") for e in acl}
    for usuario in sorted(faltantes):
        print(f"AVISO: {usuario} no tiene ACL en EMQX; no se modifica.")

    print(f"{len(acl)} usuarios con ACL; {len(cambios)} por actualizar.")
    for usuario, reglas in cambios:
        print(f"  {usuario}")
        for regla in reglas:
            print(f"      {regla['permission']:5} {regla['action']:9} {regla['topic']}")

    if not args.aplicar:
        print("\nSimulación: no se escribió nada. Repite con --aplicar para guardar.")
        return 0

    errores = 0
    for usuario, reglas in cambios:
        try:
            servicio.reemplazar_acl(usuario, reglas)
        except Exception as e:  # noqa: BLE001 - se reporta y se sigue con el resto
            errores += 1
            print(f"ERROR en {usuario}: {e}", file=sys.stderr)
    print(f"Listo: {len(cambios) - errores} actualizados, {errores} con error.")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
