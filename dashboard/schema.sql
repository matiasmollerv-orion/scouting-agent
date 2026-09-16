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
