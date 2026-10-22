-- =====================================================================
-- 02 — Estructura: enum de reservas, columnas nuevas, tablas auxiliares
--      e índices. Requiere haber ejecutado 01 antes.
-- Se puede volver a ejecutar sin error (idempotente).
-- Nota: asume que la tabla de usuarios es public.usuarios.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Enum de estado de reserva y reasignación de reservas.estado
-- ---------------------------------------------------------------------
do $$
begin
    if not exists (select 1 from pg_type where typname = 'estado_reserva_enum') then
        create type public.estado_reserva_enum as enum
            ('pendiente_llegada', 'en_uso', 'finalizada', 'cancelada', 'expirada');
    end if;
end$$;

do $$
begin
    -- Solo si la columna todavía usa el enum anterior (activo/inactivo)
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'reservas'
          and column_name = 'estado' and udt_name = 'estado_general_enum'
    ) then
        -- El índice parcial depende del tipo de la columna: se elimina y se recrea abajo
        drop index if exists public.uq_una_reserva_activa_por_usuario;

        alter table public.reservas alter column estado drop default;
        alter table public.reservas alter column estado type public.estado_reserva_enum
            using (case
                       when estado = 'activo' and fecha_llegada is not null then 'en_uso'
                       when estado = 'activo' then 'pendiente_llegada'
                       else 'finalizada'
                   end)::public.estado_reserva_enum;
        alter table public.reservas alter column estado set default 'pendiente_llegada';
    end if;
end$$;

-- RF-09: un estudiante no puede tener dos reservas vigentes
create unique index if not exists uq_una_reserva_activa_por_usuario
    on public.reservas (id_usuario_estudiante)
    where estado in ('pendiente_llegada', 'en_uso');

-- Un cajón no puede tener dos reservas vigentes a la vez
create unique index if not exists uq_una_reserva_activa_por_cajon
    on public.reservas (id_cajon)
    where estado in ('pendiente_llegada', 'en_uso');

-- ---------------------------------------------------------------------
-- 2. Columnas nuevas en reservas
-- ---------------------------------------------------------------------
alter table public.reservas add column if not exists vehiculo_detectado boolean not null default false;
alter table public.reservas add column if not exists notificado_retraso boolean not null default false;
alter table public.reservas add column if not exists notificado_fin_proximo boolean not null default false;
alter table public.reservas add column if not exists notificado_fin boolean not null default false;

-- fecha_usuario = fecha y hora en que el estudiante creó la reserva
update public.reservas set fecha_usuario = now() where fecha_usuario is null;
alter table public.reservas alter column fecha_usuario set default now();
alter table public.reservas alter column fecha_usuario set not null;
comment on column public.reservas.fecha_usuario is 'Fecha y hora en que el estudiante creó la reserva.';
comment on column public.reservas.cronometro is 'Plazo límite de llegada (1 h desde la confirmación). Se pone en NULL al registrar la llegada; el fin de uso es fecha_fin.';
comment on column public.reservas.vehiculo_detectado is 'true cuando el sensor detectó el vehículo después de registrar la llegada (permite el RF-14).';

-- Índice para la lista de reservas del administrador (filtra por estado, ordena por creación)
create index if not exists idx_reservas_estado_fecha_usuario
    on public.reservas (estado, fecha_usuario desc);

-- ---------------------------------------------------------------------
-- 3. cajones.estado_sensor: última lectura física del nodo.
--    estado_actual pasa a ser el estado efectivo (sensor + bloqueo + reserva).
-- ---------------------------------------------------------------------
alter table public.cajones
    add column if not exists estado_sensor public.estado_cajon_enum not null default 'no_conectado';

update public.cajones
   set estado_sensor = estado_actual
 where estado_sensor = 'no_conectado' and estado_actual in ('libre', 'ocupado');

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'chk_cajones_estado_sensor') then
        alter table public.cajones add constraint chk_cajones_estado_sensor
            check (estado_sensor in ('libre', 'ocupado', 'no_conectado'));
    end if;
end$$;

comment on column public.cajones.estado_sensor is 'Última lectura del sensor (libre, ocupado o no_conectado). estado_actual es el estado efectivo que ve la app.';

-- ---------------------------------------------------------------------
-- 4. Configuración editable (reglas de negocio ajustables sin redesplegar)
-- ---------------------------------------------------------------------
create table if not exists public.config_sistema (
    clave        text primary key,
    valor        text not null,
    descripcion  text
);
alter table public.config_sistema enable row level security;  -- sin políticas: solo el backend la lee
revoke all on public.config_sistema from anon, authenticated;

insert into public.config_sistema (clave, valor, descripcion) values
    ('zona_horaria',           'America/Mexico_City', 'Zona horaria del instituto'),
    ('hora_apertura',          '06:00', 'Inicio del horario de operación'),
    ('hora_cierre',            '22:00', 'Fin del horario de operación'),
    ('duracion_max_h',         '15',    'Duración máxima de una reserva (horas)'),
    ('cronometro_llegada_min', '60',    'Minutos para llegar desde la confirmación (RF-06)'),
    ('tolerancia_min',         '20',    'Minutos de tolerancia tras el cronómetro (RF-07)'),
    ('aviso_fin_min',          '10',    'Minutos antes del fin de la reserva en que se avisa (PROPUESTA, por confirmar)'),
    ('bloqueo_ttl_s',          '120',   'Segundos que un estudiante puede tener bloqueado un cajón mientras reserva (PROPUESTA, por confirmar)')
on conflict (clave) do nothing;

-- ---------------------------------------------------------------------
-- 5. Bloqueos temporales de cajón (tabla separada: la app no debe ver quién bloquea)
-- ---------------------------------------------------------------------
create table if not exists public.bloqueos_cajon (
    id_cajon         smallint primary key references public.cajones(id_cajon) on delete cascade,
    id_usuario       uuid not null unique references public.usuarios(id_usuario) on delete cascade,
    bloqueado_hasta  timestamptz not null
);
comment on table public.bloqueos_cajon is 'Bloqueo temporal (RF-02): un cajón por estudiante y un estudiante por cajón.';
alter table public.bloqueos_cajon enable row level security;  -- sin políticas: solo el backend
revoke all on public.bloqueos_cajon from anon, authenticated;

-- ---------------------------------------------------------------------
-- 6. Tokens FCM de los dispositivos (notificaciones push)
-- ---------------------------------------------------------------------
create table if not exists public.dispositivos_fcm (
    id_dispositivo       uuid primary key default gen_random_uuid(),
    id_usuario           uuid not null references public.usuarios(id_usuario) on delete cascade,
    token                text not null unique,
    plataforma           text not null check (plataforma in ('android', 'ios')),
    fecha_actualizacion  timestamptz not null default now()
);
create index if not exists idx_dispositivos_fcm_usuario on public.dispositivos_fcm(id_usuario);
alter table public.dispositivos_fcm enable row level security;

drop policy if exists dispositivos_fcm_select_propio on public.dispositivos_fcm;
create policy dispositivos_fcm_select_propio on public.dispositivos_fcm
    for select using (id_usuario = auth.uid());

drop policy if exists dispositivos_fcm_delete_propio on public.dispositivos_fcm;
create policy dispositivos_fcm_delete_propio on public.dispositivos_fcm
    for delete using (id_usuario = auth.uid());
-- El alta/actualización del token se hace con la función registrar_token_fcm (script 05).
