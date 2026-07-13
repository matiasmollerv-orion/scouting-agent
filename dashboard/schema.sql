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
  fit_tesis text,
  next_step text,
  valida_idea_propia text,
  fundadores text,
  redes_sociales text,
  fit_yc text,
  cost_usd numeric
);

-- Migración para tablas creadas antes de estos campos (idempotente,
-- correr en el SQL editor si la tabla ya existía):
alter table scouting_deep_ondemand add column if not exists valida_idea_propia text;
alter table scouting_deep_ondemand add column if not exists fundadores text;
alter table scouting_deep_ondemand add column if not exists redes_sociales text;
alter table scouting_deep_ondemand add column if not exists fit_yc text;
