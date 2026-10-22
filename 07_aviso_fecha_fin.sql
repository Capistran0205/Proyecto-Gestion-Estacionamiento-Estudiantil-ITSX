-- =====================================================================
-- 07 — Aviso al llegar la fecha_fin de una reserva en uso
-- SOLO para quien ya ejecutó los scripts 02, 04 y 05 antes de este cambio.
-- (Si aún no los has ejecutado, no necesitas este script: ya lo incluyen.)
-- Se puede volver a ejecutar sin error.
-- =====================================================================

alter table public.reservas add column if not exists notificado_fin boolean not null default false;

-- CREATE OR REPLACE conserva los permisos que dio el script 05.

create or replace function public.extender_reserva(p_id_usuario uuid, p_id_reserva uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_r         public.reservas%rowtype;
    v_nuevo_fin timestamptz;
begin
    select * into v_r from public.reservas
     where id_reserva = p_id_reserva and id_usuario_estudiante = p_id_usuario
     for update;
    if not found then
        raise exception 'La reserva no existe o no te pertenece.' using hint = 'RESERVA_NO_ENCONTRADA';
    end if;
    if v_r.estado <> 'en_uso' then
        raise exception 'Solo puedes extender una reserva que ya está en uso.' using hint = 'ESTADO_INVALIDO';
    end if;

    v_nuevo_fin := v_r.fecha_fin + interval '1 hour';
    begin
        perform public.validar_ventana_reserva(v_r.fecha_inicio, v_nuevo_fin);
    exception when others then
        raise exception 'No puedes extender: se excedería el horario de operación o la duración máxima.'
            using hint = 'EXTENSION_NO_PERMITIDA';
    end;

    update public.reservas
       set fecha_fin = v_nuevo_fin, notificado_fin_proximo = false, notificado_fin = false
     where id_reserva = p_id_reserva;

    return jsonb_build_object('id_reserva', p_id_reserva, 'id_cajon', v_r.id_cajon,
                              'fecha_fin', v_nuevo_fin);
end;
$$;

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
                   where estado = 'en_uso' and not notificado_fin and now() >= fecha_fin);
$$;

create or replace function public.barrido_reservas()
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_tol       interval := make_interval(mins => public.cfg('tolerancia_min')::int);
    v_aviso     interval := make_interval(mins => public.cfg('aviso_fin_min')::int);
    v_cajones   jsonb := '[]'::jsonb;
    v_retrasos  jsonb;
    v_expiradas jsonb;
    v_fin       jsonb;
    v_fin_alc   jsonb;
    v_ids       smallint[];
    v_id        smallint;
    v_item      jsonb;
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

    return jsonb_build_object(
        'cajones',       v_cajones,
        'retrasos',      v_retrasos,
        'expiradas',     v_expiradas,
        'fin_proximo',   v_fin,
        'fin_alcanzado', v_fin_alc
    );
end;
$$;
