# Scouting Agent — Contexto para brainstorming y discusión de ideas

Este repo corre un pipeline semanal que evalúa ~30 ideas de negocio de
fuentes internacionales (HN, YC, TechCrunch, prensa industrial, etc.) contra
la tesis de founder de Matías, y manda un email los sábados con las mejores.

Esta sesión es para DISCUTIR y evaluar ideas — no para tocar el pipeline en
sí (ingeniería, prompts, deploys). Si el pedido es cambiar código del
sistema, decilo explícitamente antes de tocar nada.

## Dónde están los datos

- `reports/AAAA-Wnn.md` — reporte legible de cada semana. Lista TODAS las
  ideas analizadas en profundidad (hasta 8), no solo las ~7 del email.
- `reports/AAAA-Wnn-full.json` — dataset completo: triage de las ~30 +
  deep de las analizadas, con todos los campos (score, `tipo_candidato`,
  `fit_yc`, `valida_idea_propia`, etc.)
- `prompts/score.md` — la tesis completa del fundador: categorías de alto
  interés y exclusiones. Es el marco de evaluación — usalo, no inventes otro.
- `prompts/ideas_propias.md` — las tesis que Matías ya brainstormeó antes
  (longevidad B2B2C, frontline workers, exportadoras de fruta, etc.), contra
  las que se cruza cada candidato nuevo.
- Dashboard en vivo (historial completo + análisis on-demand):
  https://scouting-agent-evhaywjskshfzrq75knnd4.streamlit.app/

## GBrain (segundo cerebro de Matías)

Las herramientas `mcp__gbrain__*` están disponibles en cualquier sesión
(config global, no exclusiva de este proyecto). Antes de sugerir algo como
"nuevo", buscá si ya se pensó:

- `search` / `query` / `recall` — buscar qué ya existe sobre un tema.
- Los reportes semanales del scouting se capturan automáticamente a GBrain
  — también son buscables ahí, no solo en este repo.

## Cómo evaluar una idea en esta sesión

1. Si viene del scouting semanal, leé el reporte real de esa semana primero
   (no evalúes de memoria ni inventes datos).
2. Buscá en GBrain si se relaciona con algo que Matías ya pensó o discutió.
3. Usá los criterios de `prompts/score.md` (problema real, barrera de
   entrada, replicabilidad en Chile, ventana de tiempo, tamaño de mercado)
   como marco de discusión.
4. No des solo opinión — señalá gaps de información y el próximo paso
   concreto de validación.
