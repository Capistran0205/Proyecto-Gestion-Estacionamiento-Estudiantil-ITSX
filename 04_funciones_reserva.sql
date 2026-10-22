-- =====================================================================
-- 04 — Funciones de negocio de la reserva
-- Las llama el backend (Edge Functions) con service_role, pasando el id del
-- usuario ya validado por JWT. El script 05 les quita el acceso a anon y
-- authenticated. Requiere 01, 02 y 03. Se puede volver a ejecutar.
-- Todas las funciones de transición devuelven jsonb; los errores de regla
-- de negocio llevan un código en HINT (p. ej. 'CAJON_BLOQUEADO') que el
-- backend traduce a la respuesta para la app.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Configuración
-- ---------------------------------------------------------------------
create or replace function public.cfg(p_clave text)
returns text
language sql
stable
security definer
set search_path = public
as $$
    select valor from public.config_sistema where clave = p_clave;
$$;

-- RF-01: la hora de inicio es la siguiente hora en punto (hora local del instituto)
create or replace function public.proxima_hora_en_punto(p_ahora timestamptz default now())
returns timestamptz
language sql
stable
security definer
set search_path = public
as $$
    select (date_trunc('hour', (p_ahora at time zone public.cfg('zona_horaria'))) + interval '1 hour')
           at time zone public.cfg('zona_horaria');
$$;

-- RF-04: valida horario de operación, mismo día y duración máxima
create or replace function public.validar_ventana_reserva(p_inicio timestamptz, p_fin timestamptz)
returns void
language plpgsql
stable
security definer
set search_path = public
as $$
declare
    v_zona     text     := public.cfg('zona_horaria');
    v_apertura time     := public.cfg('hora_apertura')::time;
    v_cierre   time     := public.cfg('hora_cierre')::time;
    v_max      interval := make_interval(hours => public.cfg('duracion_max_h')::int);
    v_ini      timestamp := (p_inicio at time zone v_zona);
    v_fin      timestamp := (p_fin at time zone v_zona);
begin
    if p_fin <= p_inicio then
        raise exception 'La hora de fin debe ser posterior a la hora de inicio.'
            using hint = 'FIN_INVALIDO';
    end if;
    if v_ini::time < v_apertura or v_ini::time >= v_cierre then
        raise exception 'La hora de inicio queda fuera del horario de operación (% a %).',
            public.cfg('hora_apertura'), public.cfg('hora_cierre')
            using hint = 'FUERA_DE_HORARIO';
    end if;
    if v_fin::date <> v_ini::date then
        raise exception 'La reserva debe terminar el mismo día en que inicia.'
            using hint = 'OTRO_DIA';
    end if;
    if v_fin::time > v_cierre then
        raise exception 'La hora de fin excede el horario de operación (cierre a las %).',
            public.cfg('hora_cierre')
            using hint = 'FUERA_DE_HORARIO';
    end if;
    if (p_fin - p_inicio) > v_max then
        raise exception 'La duración máxima de una reserva es de % horas.',
            public.cfg('duracion_max_h')
            using hint = 'DURACION_EXCEDIDA';
    end if;
end;
$$;

-- ---------------------------------------------------------------------
-- Estado efectivo de un cajón (única fuente de verdad en la base de datos)
--   1. sensor no_conectado                    -> no_conectado
--   2. sensor ocupado                         -> ocupado   (la lectura física manda, RNF-01)
--   3. reserva pendiente_llegada, o en_uso    -> reservado
--      sin vehículo detectado todavía
--   4. bloqueo temporal vigente               -> bloqueado
--   5. en otro caso                           -> libre
-- Toma el candado de fila del cajón, por lo que serializa las operaciones
-- concurrentes sobre el mismo cajón. estado_sistema es lo que se publica
-- en MQTT: 'bloqueado' | 'reservado' | 'liberado'.
-- ---------------------------------------------------------------------
create or replace function public.recalcular_estado_cajon(p_id_cajon smallint)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_c         public.cajones%rowtype;
    v_reservado boolean;
    v_bloqueado boolean;
    v_nuevo     public.estado_cajon_enum;
    v_sistema   text;
begin
    select * into v_c from public.cajones where id_cajon = p_id_cajon for update;
    if not found then
        raise exception 'El cajón % no existe.', p_id_cajon using hint = 'CAJON_NO_EXISTE';
    end if;

    -- Reservado: pendiente de llegada, o en uso sin el vehículo en el cajón
    -- (aún no detectado, o con la salida del RF-14 por confirmar; libre_desde se crea en 05)
    select exists (
        select 1 from public.reservas r
        where r.id_cajon = p_id_cajon
          and (r.estado = 'pendiente_llegada'
               or (r.estado = 'en_uso'
                   and (not r.vehiculo_detectado or r.libre_desde is not null)))
    ) into v_reservado;

    select exists (
        select 1 from public.bloqueos_cajon b
        where b.id_cajon = p_id_cajon and b.bloqueado_hasta > now()
    ) into v_bloqueado;

    v_nuevo := (case
                    when v_c.estado_sensor = 'no_conectado' then 'no_conectado'
                    when v_c.estado_sensor = 'ocupado'      then 'ocupado'
                    when v_reservado                        then 'reservado'
                    when v_bloqueado                        then 'bloqueado'
                    else 'libre'
                end)::public.estado_cajon_enum;

    v_sistema := case
                     when v_reservado then 'reservado'
                     when v_bloqueado then 'bloqueado'
                     else 'liberado'
                 end;

    if v_c.estado_actual is distinct from v_nuevo then
        update public.cajones set estado_actual = v_nuevo where id_cajon = p_id_cajon;
    end if;

    return jsonb_build_object(
        'id_cajon',        p_id_cajon,
        'etiqueta',        v_c.etiqueta,
        'estado_anterior', v_c.estado_actual,
        'estado_nuevo',    v_nuevo,
        'cambio',          (v_c.estado_actual is distinct from v_nuevo),
        'estado_sensor',   v_c.estado_sensor,
        'estado_sistema',  v_sistema
    );
end;
$$;

-- ---------------------------------------------------------------------
-- RF-02: bloqueo temporal al seleccionar un cajón libre
-- Devuelve la hora de inicio (fija) y el rango de horas de fin válido.
-- ---------------------------------------------------------------------
create or replace function public.bloquear_cajon(
    p_id_usuario uuid,
    p_id_cajon   smallint,
    p_ahora      timestamptz default now()
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_zona      text := public.cfg('zona_horaria');
    v_inicio    timestamptz := public.proxima_hora_en_punto(p_ahora);
    v_ini_local timestamp := (public.proxima_hora_en_punto(p_ahora) at time zone public.cfg('zona_horaria'));
    v_activo    boolean;
    v_cajon     public.cajones%rowtype;
    v_ids       smallint[];
    v_id        smallint;
    v_liberados jsonb := '[]'::jsonb;
    v_rc        jsonb;
    v_estado    text;
    v_dueno     uuid;
    v_hasta     timestamptz;
    v_fin_max   timestamptz;
begin
    select (estado_cuenta = 'activo') into v_activo
      from public.usuarios where id_usuario = p_id_usuario;
    if v_activo is distinct from true then
        raise exception 'Tu cuenta no está activa.' using hint = 'CUENTA_INACTIVA';
    end if;

    -- RF-09
    if exists (select 1 from public.reservas
               where id_usuario_estudiante = p_id_usuario
                 and estado in ('pendiente_llegada', 'en_uso')) then
        raise exception 'Ya tienes una reserva activa.' using hint = 'RESERVA_ACTIVA';
    end if;

    if v_ini_local::time < public.cfg('hora_apertura')::time
       or v_ini_local::time >= public.cfg('hora_cierre')::time then
        raise exception 'No se pueden hacer reservas fuera del horario de operación (% a %).',
            public.cfg('hora_apertura'), public.cfg('hora_cierre')
            using hint = 'FUERA_DE_HORARIO';
    end if;

    select * into v_cajon from public.cajones where id_cajon = p_id_cajon;
    if not found then
        raise exception 'El cajón no existe.' using hint = 'CAJON_NO_EXISTE';
    end if;
    if not v_cajon.estado_actividad then
        raise exception 'El cajón está fuera de servicio.' using hint = 'CAJON_INACTIVO';
    end if;

    -- Un estudiante solo puede tener un cajón bloqueado a la vez
    with d as (
        delete from public.bloqueos_cajon
         where id_usuario = p_id_usuario and id_cajon <> p_id_cajon
        returning id_cajon
    )
    select coalesce(array_agg(id_cajon), '{}') into v_ids from d;
    foreach v_id in array v_ids loop
        v_liberados := v_liberados || jsonb_build_array(public.recalcular_estado_cajon(v_id));
    end loop;

    -- Candado de fila del cajón + estado al día
    v_rc := public.recalcular_estado_cajon(p_id_cajon);
    v_estado := v_rc->>'estado_nuevo';
    select id_usuario into v_dueno from public.bloqueos_cajon
     where id_cajon = p_id_cajon and bloqueado_hasta > now();

    if v_estado = 'no_conectado' then
        raise exception 'El cajón no está disponible porque no tiene conexión.' using hint = 'CAJON_NO_CONECTADO';
    elsif v_estado = 'ocupado' then
        raise exception 'El cajón está ocupado.' using hint = 'CAJON_OCUPADO';
    elsif v_estado = 'reservado' then
        raise exception 'El cajón ya fue reservado.' using hint = 'CAJON_RESERVADO';
    elsif v_estado = 'bloqueado' and v_dueno is distinct from p_id_usuario then
        raise exception 'Otro estudiante está reservando este cajón en este momento.' using hint = 'CAJON_BLOQUEADO';
    end if;

    v_hasta := now() + make_interval(secs => public.cfg('bloqueo_ttl_s')::int);
    insert into public.bloqueos_cajon (id_cajon, id_usuario, bloqueado_hasta)
    values (p_id_cajon, p_id_usuario, v_hasta)
    on conflict (id_cajon) do update
        set id_usuario = excluded.id_usuario,
            bloqueado_hasta = excluded.bloqueado_hasta;

    v_rc := public.recalcular_estado_cajon(p_id_cajon);

    v_fin_max := least(
        ((date_trunc('day', v_ini_local) + public.cfg('hora_cierre')::time) at time zone v_zona),
        v_inicio + make_interval(hours => public.cfg('duracion_max_h')::int)
    );

    return jsonb_build_object(
        'cajon',             v_rc,
        'cajones_liberados', v_liberados,
        'bloqueado_hasta',   v_hasta,
        'fecha_inicio',      v_inicio,
        'fin_minimo',        v_inicio + interval '1 hour',
        'fin_maximo',        v_fin_max
    );
end;
$$;

-- RF-03: el estudiante cancela el flujo -> libera su bloqueo de inmediato
create or replace function public.liberar_bloqueo(p_id_usuario uuid, p_id_cajon smallint default null)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_ids smallint[];
    v_id  smallint;
    v_res jsonb := '[]'::jsonb;
begin
    with d as (
        delete from public.bloqueos_cajon
         where id_usuario = p_id_usuario
           and (p_id_cajon is null or id_cajon = p_id_cajon)
        returning id_cajon
    )
    select coalesce(array_agg(id_cajon), '{}') into v_ids from d;
    foreach v_id in array v_ids loop
        v_res := v_res || jsonb_build_array(public.recalcular_estado_cajon(v_id));
    end loop;
    return jsonb_build_object('cajones', v_res);
end;
$$;

-- ---------------------------------------------------------------------
-- RF-05 / RF-06 / RF-09: confirmar la reserva
-- p_fecha_inicio es la hora que la app recibió de bloquear_cajon; si ya
-- cambió de hora, se pide volver a elegir.
-- ---------------------------------------------------------------------
create or replace function public.crear_reserva(
    p_id_usuario   uuid,
    p_id_cajon     smallint,
    p_fecha_inicio timestamptz,
    p_fecha_fin    timestamptz,
    p_ahora        timestamptz default now()
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_activo boolean;
    v_rc     jsonb;
    v_res    public.reservas%rowtype;
begin
    select (estado_cuenta = 'activo') into v_activo
      from public.usuarios where id_usuario = p_id_usuario;
    if v_activo is distinct from true then
        raise exception 'Tu cuenta no está activa.' using hint = 'CUENTA_INACTIVA';
    end if;

    v_rc := public.recalcular_estado_cajon(p_id_cajon);

    if not exists (select 1 from public.bloqueos_cajon
                   where id_cajon = p_id_cajon and id_usuario = p_id_usuario
                     and bloqueado_hasta > now()) then
        raise exception 'Se agotó el tiempo para completar la reserva. Selecciona el cajón de nuevo.'
            using hint = 'BLOQUEO_EXPIRADO';
    end if;
    if v_rc->>'estado_nuevo' <> 'bloqueado' then
        raise exception 'El cajón ya no está disponible.' using hint = 'CAJON_NO_DISPONIBLE';
    end if;
    if p_fecha_inicio is distinct from public.proxima_hora_en_punto(p_ahora) then
        raise exception 'La hora de inicio cambió. Vuelve a seleccionar el cajón.'
            using hint = 'INICIO_CAMBIO';
    end if;

    perform public.validar_ventana_reserva(p_fecha_inicio, p_fecha_fin);

    -- RF-09
    if exists (select 1 from public.reservas
               where id_usuario_estudiante = p_id_usuario
                 and estado in ('pendiente_llegada', 'en_uso')) then
        raise exception 'Ya tienes una reserva activa.' using hint = 'RESERVA_ACTIVA';
    end if;

    begin
        insert into public.reservas
            (id_usuario_estudiante, id_cajon, fecha_inicio, fecha_fin, estado, codigo_qr, cronometro)
        values
            (p_id_usuario, p_id_cajon, p_fecha_inicio, p_fecha_fin, 'pendiente_llegada',
             replace(gen_random_uuid()::text, '-', ''),
             now() + make_interval(mins => public.cfg('cronometro_llegada_min')::int))
        returning * into v_res;
    exception when unique_violation then
        raise exception 'No fue posible crear la reserva: ya existe una reserva activa.'
            using hint = 'RESERVA_ACTIVA';
    end;

    delete from public.bloqueos_cajon where id_cajon = p_id_cajon;
    v_rc := public.recalcular_estado_cajon(p_id_cajon);

    return jsonb_build_object(
        'id_reserva',   v_res.id_reserva,
        'codigo_qr',    v_res.codigo_qr,
        'estado',       v_res.estado,
        'id_cajon',     p_id_cajon,
        'fecha_inicio', v_res.fecha_inicio,
        'fecha_fin',    v_res.fecha_fin,
        'cronometro',   v_res.cronometro,
        'cajon',        v_rc
    );
end;
$$;

-- RF-15 / RNF-03: solo el propietario cancela, y solo antes de la llegada
create or replace function public.cancelar_reserva(p_id_usuario uuid, p_id_reserva uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_r  public.reservas%rowtype;
    v_rc jsonb;
begin
    select * into v_r from public.reservas
     where id_reserva = p_id_reserva and id_usuario_estudiante = p_id_usuario
     for update;
    if not found then
        raise exception 'La reserva no existe o no te pertenece.' using hint = 'RESERVA_NO_ENCONTRADA';
    end if;
    if v_r.estado <> 'pendiente_llegada' then
        raise exception 'Solo puedes cancelar una reserva antes de tu llegada.' using hint = 'ESTADO_INVALIDO';
    end if;

    update public.reservas set estado = 'cancelada' where id_reserva = p_id_reserva;
    v_rc := public.recalcular_estado_cajon(v_r.id_cajon);

    return jsonb_build_object('id_reserva', p_id_reserva, 'estado', 'cancelada',
                              'id_cajon', v_r.id_cajon, 'cajon', v_rc);
end;
$$;

-- RF-12 / RNF-03: extender una hora (solo reserva en uso y dentro de los límites)
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

-- RF-13 / RNF-03: el propietario confirma su salida
create or replace function public.confirmar_salida(p_id_usuario uuid, p_id_reserva uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_r  public.reservas%rowtype;
    v_rc jsonb;
begin
    select * into v_r from public.reservas
     where id_reserva = p_id_reserva and id_usuario_estudiante = p_id_usuario
     for update;
    if not found then
        raise exception 'La reserva no existe o no te pertenece.' using hint = 'RESERVA_NO_ENCONTRADA';
    end if;
    if v_r.estado <> 'en_uso' then
        raise exception 'Solo puedes confirmar la salida de una reserva en uso.' using hint = 'ESTADO_INVALIDO';
    end if;

    update public.reservas set estado = 'finalizada' where id_reserva = p_id_reserva;
    v_rc := public.recalcular_estado_cajon(v_r.id_cajon);

    return jsonb_build_object('id_reserva', p_id_reserva, 'estado', 'finalizada',
                              'id_cajon', v_r.id_cajon, 'cajon', v_rc);
end;
$$;

-- ---------------------------------------------------------------------
-- RF-10 / RF-11 / RNF-06: el administrador valida el QR y registra la llegada
-- ---------------------------------------------------------------------
create or replace function public.confirmar_llegada(p_id_admin uuid, p_codigo_qr text)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_r      public.reservas%rowtype;
    v_u      public.usuarios%rowtype;
    v_sensor public.estado_cajon_enum;
    v_rc     jsonb;
begin
    if not exists (select 1 from public.usuarios
                   where id_usuario = p_id_admin and rol = 'administrador'
                     and estado_cuenta = 'activo') then
        raise exception 'Solo un administrador puede validar códigos QR.' using hint = 'NO_AUTORIZADO';
    end if;

    select * into v_r from public.reservas where codigo_qr = trim(p_codigo_qr) for update;
    if not found then
        raise exception 'El código QR no corresponde a ninguna reserva.' using hint = 'QR_INVALIDO';
    end if;

    if v_r.estado = 'cancelada' then
        raise exception 'El código QR fue cancelado.' using hint = 'QR_CANCELADO';
    elsif v_r.estado = 'expirada' then
        raise exception 'El código QR expiró: se agotó el tiempo de llegada.' using hint = 'QR_EXPIRADO';
    elsif v_r.estado in ('en_uso', 'finalizada') then
        raise exception 'El código QR ya fue utilizado.' using hint = 'QR_USADO';
    elsif v_r.cronometro is not null
          and now() >= v_r.cronometro + make_interval(mins => public.cfg('tolerancia_min')::int) then
        raise exception 'El código QR expiró: se agotó el tiempo de llegada.' using hint = 'QR_EXPIRADO';
    end if;

    -- Candado del cajón antes de leer el sensor (evita carreras con la ingesta)
    perform 1 from public.cajones where id_cajon = v_r.id_cajon for update;
    select estado_sensor into v_sensor from public.cajones where id_cajon = v_r.id_cajon;

    update public.reservas
       set estado = 'en_uso',
           fecha_llegada = now(),
           cronometro = null,
           vehiculo_detectado = (v_sensor = 'ocupado')
     where id_reserva = v_r.id_reserva
    returning * into v_r;

    v_rc := public.recalcular_estado_cajon(v_r.id_cajon);
    select * into v_u from public.usuarios where id_usuario = v_r.id_usuario_estudiante;

    return jsonb_build_object(
        'id_reserva',    v_r.id_reserva,
        'id_usuario',    v_r.id_usuario_estudiante,
        'id_cajon',      v_r.id_cajon,
        'fecha_llegada', v_r.fecha_llegada,
        'fecha_fin',     v_r.fecha_fin,
        'estudiante',    jsonb_build_object(
                             'nombre',           v_u.nombre,
                             'apellido_paterno', v_u.apellido_paterno,
                             'apellido_materno', v_u.apellido_materno,
                             'medio_transporte', v_u.medio_transporte),
        'cajon',         v_rc
    );
end;
$$;
