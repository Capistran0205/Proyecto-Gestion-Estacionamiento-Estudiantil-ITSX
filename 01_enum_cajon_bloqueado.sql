-- =====================================================================
-- 01 — Nuevo estado "bloqueado" para los cajones
-- EJECUTAR SOLO ESTE SCRIPT, en una ejecución aparte y ANTES de los demás.
-- (Postgres no permite usar un valor de enum recién agregado dentro de la
--  misma transacción que lo agrega.)
-- =====================================================================
alter type public.estado_cajon_enum add value if not exists 'bloqueado';
