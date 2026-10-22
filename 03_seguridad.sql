-- =====================================================================
-- 03 — Seguridad: triggers de protección y ajuste de RLS en reservas
-- Se puede volver a ejecutar sin error (idempotente).
-- Nota: asume que la tabla de usuarios es public.usuarios.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Modificación de datos del estudiante
-- ---------------------------------------------------------------------

-- RNF-03: el correo institucional no se modifica (a ningún rol)
create or replace function public.proteger_correo_institucional()
returns trigger
language plpgsql
as $$
begin
    if new.correo_institucional is distinct from old.correo_institucional then
        raise exception 'El correo institucional no se puede modificar.'
            using hint = 'CORREO_NO_EDITABLE';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_proteger_correo_institucional on public.usuarios;
create trigger trg_proteger_correo_institucional
    before update on public.usuarios
    for each row execute function public.proteger_correo_institucional();

-- RF-07: no se puede cambiar el medio de transporte con una reserva vigente
create or replace function public.proteger_medio_transporte()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    if new.medio_transporte is distinct from old.medio_transporte
       and exists (
           select 1 from public.reservas
           where id_usuario_estudiante = old.id_usuario
             and estado in ('pendiente_llegada', 'en_uso')
       ) then
        raise exception 'No puedes cambiar tu medio de transporte mientras tengas una reserva activa.'
            using hint = 'RESERVA_ACTIVA';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_proteger_medio_transporte on public.usuarios;
create trigger trg_proteger_medio_transporte
    before update on public.usuarios
    for each row execute function public.proteger_medio_transporte();

-- ---------------------------------------------------------------------
-- Reservas: la app ya no inserta ni actualiza directamente (RNF-03).
-- Todo cambio pasa por las funciones del backend (service_role).
-- Se conserva la lectura: el estudiante ve las suyas y el administrador todas.
-- ---------------------------------------------------------------------
drop policy if exists reservas_insert_propio on public.reservas;
drop policy if exists reservas_update_propio_o_admin on public.reservas;
