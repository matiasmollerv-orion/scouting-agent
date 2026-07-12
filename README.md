# Agente de Scouting Semanal

Rastrea fuentes internacionales, detecta ideas de negocio con tracción y entrega
un reporte semanal en español con resumen narrativo + scoring, priorizando lo
replicable en Chile.

## Cómo funciona

```
fetch (fuentes) → normalize → prefilter (sin LLM) → score (Claude) → gate → render → reporte .md
```

El reporte queda versionado en `reports/AAAA-Wnn.md`.

## Scoring

Solo **2 criterios son numéricos** (los únicos calculables desde las fuentes):

- Señal de problema real: 0-25
- Barrera de entrada razonable: 0-15
- **Score objetivo: 0-40**

Los otros 3 criterios son **señales cualitativas** (Alta/Media/Baja + evidencia),
juicio del modelo, NO suman al número:

- Replicabilidad en Chile · Ventana de tiempo · Tamaño de mercado

**Gate para entrar al reporte:** score objetivo ≥ 24/40, replicabilidad ≠ Baja,
y al menos una señal en Alta. Máx 5 ideas, ordenadas por score desc.

Ajustá el corte con la env var `SCOUTING_MIN_OBJETIVO`.

## Fuentes

**Tier 1 (activas):** Hacker News (Algolia API), TechCrunch / Wired / MIT
(RSS), Indie Hackers (RSS). Product Hunt corre solo si definís `PRODUCTHUNT_TOKEN`.

**Tier 2 (opcional, a futuro):** se agregan escribiendo una subclase de
`Source` en `src/sources/`. El pipeline no se toca.

## Setup local

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python -m src.main
```

## Setup en GitHub Actions

1. Subí el repo a GitHub.
2. *Settings → Secrets and variables → Actions* → agregá `ANTHROPIC_API_KEY`
   (y opcionalmente `PRODUCTHUNT_TOKEN`).
3. El workflow corre los lunes 12:00 UTC y commitea el reporte.

> El commit del reporte no es decorativo: mantiene el repo "activo" y evita que
> GitHub desactive el cron tras 60 días de inactividad (free tier).

Corré a mano desde *Actions → weekly-scouting → Run workflow* para probar.

## Configuración

Todo en `src/config.py` (modelo, umbrales, keywords, feeds). El prompt de
scoring vive en `prompts/score.md` y se edita sin tocar código.

## Dashboard (`dashboard/`)

El email semanal solo muestra el top 5. Todo lo evaluado (30 candidatos con
triage + hasta 8 con análisis profundo, cada semana) ya queda en
`reports/*-full.json` pero nadie lo navega. `dashboard/app.py` es una app
Streamlit que consolida todas las semanas, permite filtrar por tema/score/gate,
y agrega un botón para pedir análisis profundo **on-demand** de cualquier idea
que solo tenga triage — sin esperar a que el pipeline automático la elija
entre las 8 finalistas.

**Costo:** leer el dashboard es $0 (solo lee JSON del repo). Cada análisis
on-demand es ~$0.008 (1 llamada directa a Sonnet por idea). Tope de 15
análisis on-demand por semana (`dashboard/db.py: WEEKLY_CAP`) como guardrail.

**Setup:**

1. Corré `dashboard/schema.sql` una vez en el SQL editor de Supabase (mismo
   proyecto que usa Financial Dashboard) para crear la tabla
   `scouting_deep_ondemand`, donde persisten los análisis on-demand.
2. Deployá en Streamlit Cloud apuntando a `dashboard/app.py` como main file.
3. Secrets en Streamlit Cloud: `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`.

**Local:**

```bash
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```
