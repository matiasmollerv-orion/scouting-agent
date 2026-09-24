-- Corre esto una vez en el SQL editor de Supabase (mismo proyecto que
-- Financial Dashboard) para habilitar la persistencia de análisis on-demand.

create table if not exists scouting_deep_ondemand (
  id bigint generated always as identity primary key,
  url text not null unique,
  week text not null,
  title text not null,
  source text not null,
  requested_at timestamptz not null default now(),
  problema_score int,
  barrera_score int,
  replicabilidad_nivel text,
  replicabilidad_evidencia text,
  ventana_nivel text,
  ventana_evidencia text,
  tamano_mercado_nivel text,
  tamano_mercado_evidencia text,
  resumen text,
  b2b_o_b2c text,
  componente_ia boolean,
  tipo_fundador text,
  mercado_actual text,
  company_url text,
  funding_raised text,
  stage text,
  por_que_ahora text,
  modelo_negocio text,
  competencia_local text,
  competencia_global text,
  fit_tesis text,
  next_step text,
  valida_idea_propia text,
  fundadores text,
  redes_sociales text,
  fit_yc text,
  tipo_candidato text,
  cost_usd numeric
);

-- Migración para tablas creadas antes de estos campos (idempotente,
-- correr en el SQL editor si la tabla ya existía):
alter table scouting_deep_ondemand add column if not exists valida_idea_propia text;
alter table scouting_deep_ondemand add column if not exists fundadores text;
alter table scouting_deep_ondemand add column if not exists redes_sociales text;
alter table scouting_deep_ondemand add column if not exists fit_yc text;
alter table scouting_deep_ondemand add column if not exists tipo_candidato text;
alter table scouting_deep_ondemand add column if not exists competencia_global text;

-- 2026-09: favoritos — marcar ideas para no perderlas de vista. Guarda solo
-- el url (clave real de la idea en reports/*-full.json) + metadata liviana
-- para no duplicar todo el análisis, que ya vive en full.json o en
-- scouting_deep_ondemand si fue on-demand.
create table if not exists scouting_favorites (
  id bigint generated always as identity primary key,
  url text not null unique,
  title text not null,
  note text,
  favorited_at timestamptz not null default now()
);

-- 2026-09: análisis de MERCADO (no de empresa) — metodología de 8 pasos
-- (Aulet beachhead, TAM bottom-up+top-down, Porter, JTBD, WTP estimado/
-- validado con umbral Steve Blank, fit fundador vs prompts/score.md, RAT,
-- regulación). Ver prompts/market_analysis.md. Cola manual, disparada por
-- Matías desde el dashboard o desde una sesión de Claude Code — nunca
-- automática.
--
-- El SUJETO es el mercado/oportunidad (market_name), NO una empresa — una
-- empresa de referencia (Decade, Farther) solo ilustra que el mercado
-- existe, puede haber varias, y el análisis puede no venir de ningún
-- candidato del dashboard (ej: salió de una sesión de ideación). Por eso
-- `empresas_referentes` es texto libre separado, y `source_url` es
-- opcional (solo se llena cuando SÍ vino de un candidato puntual del
-- dashboard, como metadata de origen, no como el sujeto del análisis).
create table if not exists scouting_market_analysis (
  id bigint generated always as identity primary key,
  market_name text not null,       -- la OPORTUNIDAD/mercado, ej: "asesoría
                                    -- de inversión IA para clase media
                                    -- chilena que ya invierte" — no un
                                    -- nombre de empresa
  empresas_referentes text,        -- ej: "Decade (Brasil), Farther (EEUU)"
  source_url text,                 -- candidato del dashboard que lo disparó (opcional)
  origen text not null default 'manual',  -- 'dashboard' | 'manual' | 'chat'
  beachhead_hint text,  -- hipótesis pre-discutida ANTES del análisis caro
  context_note text,    -- lo que Matías agrega al encolar (opcional)
  status text not null default 'queued',  -- 'queued' | 'analizando' | 'listo' | 'error'
  requested_at timestamptz not null default now(),
  completed_at timestamptz,
  cost_usd numeric,
  error_detail text,
  -- Esquema fijo de salida (los 13 campos del prompt), texto libre con
  -- evidencia embebida — no JSON anidado, para tabular fácil en el
  -- comparador del dashboard.
  beachhead_definido text,
  tam_bottom_up text,
  tam_top_down text,
  discrepancia_tam text,
  competencia_global text,
  competencia_local text,
  competencia_en_beachhead_especifico text,
  dolor_jtbd text,
  wtp_estimado text,
  wtp_validado text,
  fit_fundador text,
  rat_supuesto text,
  rat_prueba_barata text,
  regulacion text
);

-- 2026-09: ORACLE — minería mensual de necesidades por país × lente (ver
-- src/oracle/matrix.py y prompts/oracle_mining.md). Todo PRIVADO: las semillas
-- nacen de fuentes públicas, pero los veredictos y motivos de Matías no deben
-- salir de acá (el repo y los logs de Actions son públicos — el runner nunca
-- imprime contenido del Vault ni de las lessons, solo conteos y costos).
create table if not exists scouting_vault (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  run_month text not null,              -- '2026-10'
  country text not null,
  lens text not null,
  tipo_senal text,                      -- queja | brecha | fuerza_externa | oferta
  necesidad text not null,
  quien text,
  evidencia text,
  fuente_url text,
  url_estado text,                      -- ok | bloqueada | rota | sin_url (chequeo automático, barato)
  solucion_existente text,
  transferencia text,                   -- hipótesis de transferencia a Chile/LatAm
  modelo text,                          -- modelo que la minó
  dedupe_key text unique,               -- evita repetir la misma semilla en corridas repetidas
  -- consejo de críticos (rubric SIN penalizar fit del fundador, solo bonus 0-1)
  s_evidencia numeric, s_tamano numeric, s_ahora numeric, s_hueco numeric,
  s_testeabilidad numeric, bonus_fit numeric, score numeric,
  objeciones text, veredicto_consejo text,
  -- nueva | en_vault (score >= umbral) | descartada_consejo | elegida | descartada | guardada
  status text not null default 'nueva',
  -- veredicto humano (alimenta scouting_lessons)
  human_verdict text, human_reason text, verdict_at timestamptz,
  market_analysis_id bigint,            -- si se eligió, fila en scouting_market_analysis
  cluster_id bigint,                    -- tema repetido entre países (lo asigna scripts/oracle_run.py)
  cluster_label text
);

-- Migración para la tabla YA creada (2026-09-20, agrupar semillas repetidas entre países):
alter table scouting_vault add column if not exists cluster_id bigint;
alter table scouting_vault add column if not exists cluster_label text;

-- Aprendizaje: cada veredicto de Matías + su motivo. El consejo lee las últimas
-- para calibrar gusto (NO para penalizar falta de experiencia — regla dura).
create table if not exists scouting_lessons (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  verdict text not null,                -- elegida | descartada | guardada
  reason text,
  seed_snapshot text,                   -- necesidad + país + lente, para contexto
  active boolean not null default true
);

-- Una fila por mes: idempotencia (no correr dos veces el mismo mes) y costo real.
create table if not exists scouting_oracle_runs (
  month_key text primary key,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'corriendo',   -- corriendo | listo | error
  pairs int, seeds int, cost_usd numeric, note text
);

-- 2026-09-24: diseño del servicio AI-native (Paso 9 del análisis, solo lente "Servicios operados por IA").
alter table scouting_market_analysis add column if not exists diseno_servicio_ia text;
