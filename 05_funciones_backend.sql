-- =====================================================================
-- 05 — Funciones del backend: ingesta del sensor, barrido periódico,
--      token FCM y permisos. Requiere 01–04. Se puede volver a ejecutar.
-- =====================================================================

-- ---------------------------------------------------------------------
-- RF-14 con confirmación: una lectura 'libre' ya no finaliza la reserva en
-- uso; solo anota desde cuándo está libre el cajón. El barrido la finaliza si
-- en salida_confirmacion_s segundos no llega otra lectura 'ocupado'. Evita que
-- una lectura falsa o momentánea del sensor termine una reserva en uso.
-- ---------------------------------------------------------------------
alter table public.reservas add column if not exists libre_desde timestamptz;
comment on column public.reservas.libre_desde is
    'Reserva en uso: momento en que el sensor reportó el cajón libre (salida por confirmar, RF-14). NULL si el vehículo sigue ahí.';

insert into public.config_sistema (clave, valor, descripcion) values
    ('salida_confirmacion_s', '30', 'Segundos que el sensor debe seguir libre para finalizar una reserva en uso (RF-14)')
on conflict (clave) do nothing;

-- ---------------------------------------------------------------------
-- Ingesta de la lectura de un sensor (la llama la Edge Function ingesta-sensor)
-- p_estado: 'libre' | 'ocupado' | 'no conectado' (también acepta 'no_conectado')
-- Devuelve qué cambió para que el backend publique en MQTT, escriba el
-- evento en Firestore (solo si hubo cambio) y envíe avisos.
--   conflicto: 'reservado' | 'bloqueado' | null  -> llegó un vehículo a un
--   cajón reservado o bloqueado (decisión de negocio pendiente: solo se informa).
--   reserva_finalizada: siempre null; la salida del RF-14 la confirma el
--   barrido (se conserva la clave para la Edge Function).
-- ---------------------------------------------------------------------
create or replace function public.registrar_lectura_sensor(p_id_cajon smallint, p_estado text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_txt       text := replace(lower(trim(coalesce(p_estado, ''))), ' ', '_');
    v_nuevo     public.estado_cajon_enum;
    v_prev      public.estado_cajon_enum;
    v_conflicto text := null;
    v_rc        jsonb;
begin
    if v_txt not in ('libre', 'ocupado', 'no_conectado') then
        raise exception 'Estado de sensor no válido: %', p_estado using hint = 'ESTADO_SENSOR_INVALIDO';
    end if;
    v_nuevo := v_txt::public.estado_cajon_enum;

    select estado_sensor into v_prev from public.cajones where id_cajon = p_id_cajon for update;
    if not found then
        raise exception 'El cajón % no existe.', p_id_cajon using hint = 'CAJON_NO_EXISTE';
    end if;

    update public.cajones set estado_sensor = v_nuevo where id_cajon = p_id_cajon;

    if v_nuevo = 'ocupado' then
        -- El vehículo del estudiante está en el cajón: habilita el RF-14 y anula
        -- una salida en espera (la lectura 'libre' anterior fue momentánea)
        update public.reservas set vehiculo_detectado = true, libre_desde = null
         where id_cajon = p_id_cajon and estado = 'en_uso'
           and (not vehiculo_detectado or libre_desde is not null);

        if v_prev is distinct from 'ocupado' then
            if exists (select 1 from public.reservas
                       where id_cajon = p_id_cajon and estado = 'pendiente_llegada') then
                v_conflicto := 'reservado';
            elsif exists (select 1 from public.bloqueos_cajon
                          where id_cajon = p_id_cajon and bloqueado_hasta > now()) then
                v_conflicto := 'bloqueado';
            end if;
        end if;

    elsif v_nuevo = 'libre' then
        -- RF-14: el vehículo de una reserva en uso parece haber salido. Solo se
        -- anota; el barrido la finaliza si el cajón sigue libre el tiempo de confirmación
        update public.reservas set libre_desde = now()
         where id_cajon = p_id_cajon and estado = 'en_uso' and vehiculo_detectado
           and libre_desde is null;

    else
        -- Sin conexión no hay lectura confiable: se anula la salida en espera
        update public.reservas set libre_desde = null
         where id_cajon = p_id_cajon and estado = 'en_uso' and libre_desde is not null;
    end if;

    v_rc := public.recalcular_estado_cajon(p_id_cajon);

    return jsonb_build_object(
        'id_cajon',               p_id_cajon,
        'estado_sensor_anterior', v_prev,
        'estado_sensor_nuevo',    v_nuevo,
        'cambio_sensor',          (v_prev is distinct from v_nuevo),
        'cajon',                  v_rc,
        'reserva_finalizada',     null,
        'conflicto',              v_conflicto
    );
end;
$$;

-- ---------------------------------------------------------------------
-- ¿Hay algo que procesar? (el Cron la consulta cada pocos segundos y solo
-- invoca la Edge Function barrido cuando devuelve true)
-- ---------------------------------------------------------------------
create or replace function public.hay_trabajo_pendiente()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (select 1 from public.bloqueos_cajon where bloqueado_hasta <= now())
        or exists (select 1 from public.reservas
                   where estado = 'pendiente_llegada' and cronometro is not null
                     and ((now() >= cronometro and not notificado_retraso)
                          or now() >= cronometro + make_interval(mins => public.cfg('tolerancia_min')::int)))
        or exists (select 1 from public.reservas
                   where estado = 'en_uso' and not notificado_fin_proximo
                     and now() >= fecha_fin - make_interval(mins => public.cfg('aviso_fin_min')::int))
        or exists (select 1 from public.reservas
                   where estado = 'en_uso' and not notificado_fin and now() >= fecha_fin)
        or exists (select 1 from public.reservas
                   where estado = 'en_uso' and libre_desde is not null
                     and now() >= libre_desde + make_interval(secs => public.cfg('salida_confirmacion_s')::int));
$$;

-- ---------------------------------------------------------------------
-- Pausa del barrido fuera del horario de operación (reduce los logs de
-- pg_cron, 2026-10-08). La ejecuta el job 'ajustar-barrido' cada 15 min y
-- activa o desactiva el job 'barrido-reservas' según config_sistema:
--   desde: hora_apertura - 75 min (se puede reservar desde 1 h antes de abrir,
--          porque el inicio es la siguiente hora en punto; +15 min por la
--          frecuencia de este job)
--   hasta: hora_cierre + tolerancia_min + 10 min (la última reserva puede
--          expirar después del cierre)
-- Acepta horarios que cruzan la medianoche. Fuera de la ventana, lo pendiente
-- (p. ej. la salida del RF-14 de una reserva en uso) espera a la reapertura.
-- Solo llama a cron.alter_job si el estado debe cambiar.
--   select cron.schedule('ajustar-barrido', '*/15 * * * *', 'select public.ajustar_barrido()');
-- ---------------------------------------------------------------------
create or replace function public.ajustar_barrido()
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
    v_ahora  time := (now() at time zone public.cfg('zona_horaria'))::time;
    v_desde  time := public.cfg('hora_apertura')::time - interval '75 minutes';
    v_hasta  time := public.cfg('hora_cierre')::time
                     + make_interval(mins => public.cfg('tolerancia_min')::int + 10);
    v_activo boolean;
    v_job    bigint;
    v_actual boolean;
begin
    v_activo := case when v_desde <= v_hasta
                     then v_ahora between v_desde and v_hasta
                     else v_ahora >= v_desde or v_ahora <= v_hasta  -- cruza la medianoche
                end;

    select jobid, active into v_job, v_actual from cron.job where jobname = 'barrido-reservas';
    if found and v_actual is distinct from v_activo then
        perform cron.alter_job(v_job, active := v_activo);
    end if;
    return v_activo;
end;
$$;

-- ---------------------------------------------------------------------
-- Barrido: libera bloqueos vencidos, marca retrasos (RF-07), expira
-- reservas (RF-08), marca avisos de fin próximo (RF-12) y de fecha_fin
-- alcanzada, y finaliza las reservas cuyo cajón siguió libre el tiempo de
-- confirmación (RF-14). Devuelve lo procesado para que la Edge Function
-- publique y notifique. Al llegar fecha_fin solo se notifica: la reserva sigue
-- en uso hasta que el estudiante confirme su salida o el sensor detecte que
-- el vehículo salió (RF-14).
-- ---------------------------------------------------------------------
create or replace function public.barrido_reservas()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_tol       interval := make_interval(mins => public.cfg('tolerancia_min')::int);
    v_aviso     interval := make_interval(mins => public.cfg('aviso_fin_min')::int);
    v_salida    interval := make_interval(secs => public.cfg('salida_confirmacion_s')::int);
    v_cajones   jsonb := '[]'::jsonb;
    v_retrasos  jsonb;
    v_expiradas jsonb;
    v_fin       jsonb;
    v_fin_alc   jsonb;
    v_salidas   jsonb := '[]'::jsonb;
    v_ids       smallint[];
    v_id        smallint;
    v_item      jsonb;
    v_r         record;
begin
    -- 1. Bloqueos vencidos (RF-03)
    with d as (
        delete from public.bloqueos_cajon where bloqueado_hasta <= now() returning id_cajon
    )
    select coalesce(array_agg(id_cajon), '{}') into v_ids from d;
    foreach v_id in array v_ids loop
        v_cajones := v_cajones || jsonb_build_array(public.recalcular_estado_cajon(v_id));
    end loop;

    -- 2. Cronómetro de llegada terminado, aún dentro de la tolerancia (RF-07)
    with r as (
        select id_reserva from public.reservas
         where estado = 'pendiente_llegada' and cronometro is not null
           and not notificado_retraso
           and now() >= cronometro and now() < cronometro + v_tol
        for update skip locked
    ), u as (
        update public.reservas x set notificado_retraso = true
          from r where x.id_reserva = r.id_reserva
        returning x.id_reserva, x.id_usuario_estudiante, x.id_cajon, x.cronometro
    )
    select coalesce(jsonb_agg(jsonb_build_object(
               'id_reserva', id_reserva, 'id_usuario', id_usuario_estudiante,
               'id_cajon', id_cajon, 'tolerancia_hasta', cronometro + v_tol)), '[]'::jsonb)
      into v_retrasos from u;

    -- 3. Tolerancia agotada: expira la reserva, invalida el QR y libera (RF-08)
    with e as (
        select id_reserva from public.reservas
         where estado = 'pendiente_llegada' and cronometro is not null
           and now() >= cronometro + v_tol
        for update skip locked
    ), u as (
        update public.reservas x set estado = 'expirada'
          from e where x.id_reserva = e.id_reserva
        returning x.id_reserva, x.id_usuario_estudiante, x.id_cajon
    )
    select coalesce(jsonb_agg(jsonb_build_object(
               'id_reserva', id_reserva, 'id_usuario', id_usuario_estudiante,
               'id_cajon', id_cajon)), '[]'::jsonb)
      into v_expiradas from u;
    for v_item in select e from jsonb_array_elements(v_expiradas) e loop
        v_cajones := v_cajones || jsonb_build_array(
            public.recalcular_estado_cajon((v_item->>'id_cajon')::smallint));
    end loop;

    -- 4. Fin de la reserva próximo (RF-12)
    with f as (
        select id_reserva from public.reservas
         where estado = 'en_uso' and not notificado_fin_proximo
           and now() >= fecha_fin - v_aviso
        for update skip locked
    ), u as (
        update public.reservas x set notificado_fin_proximo = true
          from f where x.id_reserva = f.id_reserva
        returning x.id_reserva, x.id_usuario_estudiante, x.id_cajon, x.fecha_fin
    )
    select coalesce(jsonb_agg(jsonb_build_object(
               'id_reserva', id_reserva, 'id_usuario', id_usuario_estudiante,
               'id_cajon', id_cajon, 'fecha_fin', fecha_fin)), '[]'::jsonb)
      into v_fin from u;

    -- 5. Llegó la hora de fin de la reserva
    with g as (
        select id_reserva from public.reservas
         where estado = 'en_uso' and not notificado_fin and now() >= fecha_fin
        for update skip locked
    ), u as (
        update public.reservas x set notificado_fin = true
          from g where x.id_reserva = g.id_reserva
        returning x.id_reserva, x.id_usuario_estudiante, x.id_cajon, x.fecha_fin
    )
    select coalesce(jsonb_agg(jsonb_build_object(
               'id_reserva', id_reserva, 'id_usuario', id_usuario_estudiante,
               'id_cajon', id_cajon, 'fecha_fin', fecha_fin)), '[]'::jsonb)
      into v_fin_alc from u;

    -- 6. RF-14: el cajón siguió libre el tiempo de confirmación -> el vehículo salió
    for v_r in
        select id_reserva, id_cajon from public.reservas
         where estado = 'en_uso' and libre_desde is not null
           and now() >= libre_desde + v_salida
    loop
        -- Mismo orden de candados que la ingesta (cajón y luego reserva); se
        -- vuelve a validar por si entretanto llegó una lectura 'ocupado'
        perform 1 from public.cajones where id_cajon = v_r.id_cajon for update;
        update public.reservas set estado = 'finalizada'
         where id_reserva = v_r.id_reserva and estado = 'en_uso'
           and libre_desde is not null and now() >= libre_desde + v_salida
        returning jsonb_build_object('id_reserva', id_reserva,
                                     'id_usuario', id_usuario_estudiante,
                                     'id_cajon', id_cajon) into v_item;
        if found then
            v_salidas := v_salidas || jsonb_build_array(v_item);
            v_cajones := v_cajones || jsonb_build_array(public.recalcular_estado_cajon(v_r.id_cajon));
        end if;
    end loop;

    return jsonb_build_object(
        'cajones',       v_cajones,
        'retrasos',      v_retrasos,
        'expiradas',     v_expiradas,
        'fin_proximo',   v_fin,
        'fin_alcanzado', v_fin_alc,
        'salidas',       v_salidas
    );
end;
$$;

-- ---------------------------------------------------------------------
-- Registro del token FCM del dispositivo. La llama la app (usuario con
-- sesión). Si el token ya existía con otro usuario (cambio de cuenta en el
-- mismo teléfono), pasa a pertenecer al usuario actual.
-- ---------------------------------------------------------------------
create or replace function public.registrar_token_fcm(p_token text, p_plataforma text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    if auth.uid() is null then
        raise exception 'Se requiere una sesión iniciada.' using hint = 'NO_AUTENTICADO';
    end if;
    if coalesce(trim(p_token), '') = '' then
        raise exception 'Token no válido.' using hint = 'TOKEN_INVALIDO';
    end if;

    insert into public.dispositivos_fcm (id_usuario, token, plataforma)
    values (auth.uid(), trim(p_token), p_plataforma)
    on conflict (token) do update
        set id_usuario = excluded.id_usuario,
            plataforma = excluded.plataforma,
            fecha_actualizacion = now();
end;
$$;

-- ---------------------------------------------------------------------
-- Permisos: las funciones de negocio solo las ejecuta el backend
-- (service_role). Postgres/Supabase las expone por defecto a anon y
-- authenticated; aquí se les retira. registrar_token_fcm es la excepción:
-- la llama la app con la sesión del estudiante.
-- ---------------------------------------------------------------------
do $$
declare
    r record;
begin
    for r in
        select p.oid::regprocedure as firma
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public'
          and p.proname in (
              'cfg', 'proxima_hora_en_punto', 'validar_ventana_reserva',
              'recalcular_estado_cajon', 'bloquear_cajon', 'liberar_bloqueo',
              'crear_reserva', 'cancelar_reserva', 'extender_reserva',
              'confirmar_salida', 'confirmar_llegada', 'registrar_lectura_sensor',
              'hay_trabajo_pendiente', 'barrido_reservas', 'ajustar_barrido')
    loop
        execute format('revoke all on function %s from public, anon, authenticated', r.firma);
        execute format('grant execute on function %s to service_role', r.firma);
    end loop;

    for r in
        select p.oid::regprocedure as firma
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname = 'registrar_token_fcm'
    loop
        execute format('revoke all on function %s from public, anon', r.firma);
        execute format('grant execute on function %s to authenticated, service_role', r.firma);
    end loop;
end$$;
