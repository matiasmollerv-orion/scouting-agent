from __future__ import annotations

import os

# --- Modelos (dos etapas) ---
# Triage: Haiku puntúa TODOS los candidatos con output mínimo (barato).
# Deep: Sonnet analiza en profundidad solo los mejores (calidad donde importa).
MODEL_TRIAGE = os.environ.get("SCOUTING_MODEL_TRIAGE", "claude-haiku-4-5")
MODEL_DEEP = os.environ.get("SCOUTING_MODEL_DEEP", "claude-sonnet-5")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Batch API: 50% de descuento en trabajos asíncronos. El email del sábado
# puede esperar minutos, así que siempre se intenta batch primero; si falla
# o demora demasiado, cae a llamada directa (precio completo) para que el
# reporte llegue igual.
USE_BATCH = os.environ.get("SCOUTING_USE_BATCH", "true").lower() == "true"
BATCH_TIMEOUT_MIN = int(os.environ.get("SCOUTING_BATCH_TIMEOUT_MIN", "40"))

# Guardrail de costo: si una corrida acumula más que esto, se aborta lo que
# falte y el email llega con lo que haya + advertencia. Gasto acotado por diseño.
COST_LIMIT_USD = float(os.environ.get("SCOUTING_COST_LIMIT_USD", "0.30"))

# --- Gate de scoring ---
MIN_OBJETIVO = int(os.environ.get("SCOUTING_MIN_OBJETIVO", "24"))  # sobre 40
MAX_IDEAS = 5
# El email separa "Empresas" (candidato único, estudiable) de "Tendencias"
# (análisis que cubre varios players). Sin esto, las tendencias — que suelen
# puntuar alto por agregar señal de varias empresas — desplazaban a las
# empresas concretas del top 5. Overridable por env.
MAX_IDEAS_EMPRESA = int(os.environ.get("SCOUTING_MAX_IDEAS_EMPRESA", "4"))
MAX_IDEAS_TENDENCIA = int(os.environ.get("SCOUTING_MAX_IDEAS_TENDENCIA", "3"))
# Cuántos pasan del triage al análisis profundo. Overridable por env para
# mini-runs reales baratos (ej: SCOUTING_TOP_DEEP=2 ≈ $0.01 total).
TOP_DEEP = int(os.environ.get("SCOUTING_TOP_DEEP", "8"))

# Búsquedas web reales para el deep (competencia global, ventana, por qué
# ahora) — sin esto el modelo completaba esos campos desde su prior de
# entrenamiento sin verificar nada (caso real: OpenVector vs. Clarifruit,
# feedback sesión de ideación 2026-08 — quedó "competencia_local: no
# identificada" leído como blue ocean, había un incumbente global maduro).
# Solo en deep, NUNCA en triage — ahí sí importaría el costo (30 candidatos).
#
# El prompt (score.md) instruye buscar SOLO para candidatos que cumplirían
# el gate real, o el de mayor problema_score si ninguno lo cumple — así el
# gasto escala con cuántas ideas buenas hay esa semana, no parejo para las 8.
# El tope de acá es un TECHO de seguridad, no el uso esperado.
#
# Medido en el primer run real (2026-W33, 4 búsquedas antes de este ajuste
# de prompt): cada búsqueda agregó ~$0.074 al costo del deep (el contenido
# de los resultados se inyecta como tokens de input, no es solo la tarifa
# plana de $0.01/búsqueda — ballooneó el input de ~9k a 126k tokens). Con
# esa tasa real, 4 tope ≈ $0.30 total — el techo exacto del guardrail.
MAX_WEB_SEARCHES_DEEP = int(os.environ.get("SCOUTING_MAX_WEB_SEARCHES_DEEP", "4"))

# --- Ventana temporal ---
# Solo se consideran items publicados en los últimos N días.
LOOKBACK_DAYS = int(os.environ.get("SCOUTING_LOOKBACK_DAYS", "7"))

# --- Pre-filtro (sin LLM) ---
# Umbral mínimo de engagement por fuente para pasar al análisis.
MIN_ENGAGEMENT = {
    "hackernews": 50,   # puntos en HN
    "indiehackers": 0,  # RSS sin métrica fiable, no filtra por engagement
    "techcrunch": 0,
    "wired": 0,
    "mit": 0,
    "producthunt": 20,  # votos
}

# Cantidad máxima de candidatos que llegan al triage (control de costo).
# El triage produce ~30 tokens/item, así que 30 candidatos son ~1k tokens
# de output — el pool diario justifica ver más que antes.
# Overridable por env para mini-runs reales (ej: SCOUTING_MAX_CANDIDATES=3).
MAX_CANDIDATES = int(os.environ.get("SCOUTING_MAX_CANDIDATES", "30"))

# Keywords que marcan relevancia para scouting de negocio.
# Un item pasa el pre-filtro si su engagement supera el umbral
# O si el título/texto contiene alguna de estas señales.
RELEVANCE_KEYWORDS = [
    # Señales de tracción y financiamiento
    "raised $", "raised €", "seed round", "series a", "series b",
    "pre-seed", "yc batch", "y combinator", "just launched", "we launched",
    "paying customers", "first 100 customers", "went from 0 to",
    # Tipos de producto — combos específicos, no "ai" suelto
    "ai startup", "ai saas", "ai tool for", "ai agent", "ai platform",
    "ai for", "ai-powered", "whatsapp bot", "whatsapp business",
    # Indicadores de negocio concreto
    "saas", "b2b", "b2c", "vertical saas", "marketplace", "no-code",
    "fintech", "proptech", "healthtech", "edtech", "legaltech",
    "vertical marketplace", "niche marketplace",
    # Métricas de tracción
    "mrr", "arr", "revenue", "bootstrapped", "ramen profitable",
    "1000 users", "10k users", "waitlist",
    # Señal de esfuerzo propio
    "show hn:", "i built", "we built", "i made", "side project",
    "indie hacker", "founder",
    # Tesis: B2B eficiencia operacional
    "workforce management", "field service", "deskless worker",
    "frontline worker", "employee tracking", "operations software",
    "workflow automation", "internal tools", "reporting tool",
    # Tesis: futuro del trabajo / planillas grandes — MÁXIMA prioridad,
    # sinónimos amplios para no perder señal por fraseo distinto
    "future of work", "hr tech", "hr software", "people analytics", "headcount",
    "workforce planning", "workforce management", "performance review",
    "performance management", "employee onboarding", "onboarding software",
    "shift scheduling", "staffing", "payroll", "labor management",
    "digital worker", "ai coworker", "ai employee", "ai teammate",
    "ai agents for work", "agentic workforce", "org design", "employee engagement",
    "replaces call center", "replaces support team", "automates hiring",
    "cuts headcount", "layoffs", "restructuring", "back-office automation",
    "middle management", "manager software", "internal communications",
    # Tesis: wellness / longevidad / biohacking — sinónimos amplios
    "wellness", "longevity", "biohacking", "supplement", "supplements",
    "wearable", "health coach", "mental health", "gut health", "sleep",
    "sleep tracking", "fitness app", "nutrition app", "personalized nutrition",
    "recovery", "burnout", "stress management", "corporate wellness",
    "employee benefits", "preventive health", "functional medicine",
    "hormone health", "metabolic health", "longevity clinic",
    # Tesis: ecommerce / DTC — vocabulario amplio y en lenguaje real de
    # prensa, no jerga de consultora (2026-08: "breakout brand" nunca
    # aparece en un titular real; "sold out" o "can't keep up with demand" sí).
    "dtc", "d2c", "direct-to-consumer", "direct to consumer", "ecommerce",
    "e-commerce", "online retail", "online retailer", "online store",
    "digital-first brand", "shopify", "consumer brand", "brand launch",
    "launches brand", "unveils", "debuts", "rolls out", "new product line",
    "subscription box", "membership brand", "cpg", "consumer packaged goods",
    "private label", "house brand",
    # Tesis: ecommerce — IA y herramientas que hacen tiendas más eficientes
    "product recommendation", "personalization engine", "personalized shopping",
    "dynamic pricing", "visual search", "virtual try-on", "try before you buy",
    "conversational commerce", "ai shopping", "shopping assistant",
    "product discovery", "search and discovery",
    # Tesis: ecommerce — señales de categorías/productos explotando, en
    # lenguaje real (no "breakout brand", que nadie escribe en un titular)
    "sold out", "waitlist", "can't keep up with demand", "demand surge",
    "surge in demand", "cult following", "cult favorite", "fan favorite",
    "viral on tiktok", "tiktok made me buy it", "tiktok famous", "went viral",
    "fastest-growing", "fastest growing", "gains market share", "market share",
    "hottest category", "booming category", "category creator", "fills a gap",
    "gap in the market", "expands into", "enters the market", "new category",
    "rebrand", "relaunches", "reformulates", "refreshes its", "makeover",
    # Tesis: ecommerce — categorías de producto con señal frecuente (no
    # exclusivas — solo suben la probabilidad de match real en prensa retail)
    "skincare", "beauty brand", "personal care", "haircare", "fragrance",
    "wellness brand", "pet brand", "pet care", "snack brand", "beverage brand",
    "functional beverage", "protein brand", "supplement brand", "clean label",
    "plant-based", "better-for-you", "sneaker brand", "footwear brand",
    "apparel brand", "activewear",
    # Tesis: ecommerce — infraestructura y canales nuevos
    "social commerce", "live shopping", "livestream shopping", "creator commerce",
    "creator-led brand", "fulfillment", "returns management",
    "cross-border ecommerce", "same-day delivery", "last-mile delivery",
    # Tesis: negocio tradicional reinventado — CUALQUIER industria probada con
    # una vuelta de tuerca en el cómo (entrega, modelo, tech, experiencia,
    # formato). Dos tipos de keyword: (a) señales de que algo legacy se está
    # reinventando, (b) categorías físicas concretas que la prensa tech solo
    # cubre cuando alguien las disrumpe — baja frecuencia, alta señal.
    "reinventing", "disrupting", "reimagining", "modernizing",
    "tech-enabled", "app-based", "on-demand", "legacy industry",
    "boring business", "brick-and-mortar", "traditional industry",
    "the warby parker of", "the uber of", "the airbnb of",
    "refurbished", "recommerce", "resale", "trade-in", "dark store",
    "cashierless", "autonomous store", "ghost kitchen", "cloud kitchen",
    "laundry", "car wash", "barbershop", "dry cleaning", "self-storage",
    "moving service", "grocery", "convenience store", "pharmacy", "gym",
    # Tesis: manufactura/industria tradicional reinventada — el ejemplo que
    "manufacturing startup", "contract manufacturer", "injection molding",
    "factory automation", "industrial automation", "reshoring",
    "advanced manufacturing", "small manufacturer", "family-owned factory",
    # Tesis: servicios para hogares
    "home services", "household", "home management", "cleaning service",
    # Tesis: grandes industrias chilenas
    "agtech", "mining software", "aquaculture", "precision agriculture",
    "farm management", "fishery", "commodity",
    # Tesis: clase media emergente / inclusión financiera
    "middle class", "emerging market", "financial inclusion", "remittance",
    "microfinance", "gig economy", "informal economy", "affordable",
    # Tesis: ecommerce operaciones
    "checkout", "last mile", "logistics", "retention", "loyalty program",
]

# --- Momentum de temas ---
# Conteo semanal de menciones por tema de la tesis, sobre TODO lo fetcheado
# (no solo lo que pasa el filtro). No filtra nada: solo mide. La señal es la
# aceleración entre semanas (práctica de Harmonic/Exploding Topics), no el
# número absoluto.
THEME_KEYWORDS = {
    "Futuro del trabajo": [
        "workforce", "hr tech", "people analytics", "headcount", "hiring",
        "employee", "staffing", "payroll", "shift scheduling", "frontline",
        "deskless", "future of work", "performance review",
    ],
    "IA agéntica": [
        "ai agent", "agentic", "copilot", "ai assistant", "autonomous agent",
        "ai employee", "digital worker", "second brain",
    ],
    "Wellness": [
        "wellness", "longevity", "biohacking", "sleep", "nutrition",
        "mental health", "fitness", "supplement", "health coach", "gut health",
    ],
    "Ecommerce/DTC": [
        "ecommerce", "e-commerce", "dtc", "d2c", "direct-to-consumer", "shopify",
        "checkout", "consumer brand", "brand launch", "unveils", "debuts",
        "retail tech", "last mile", "same-day delivery", "subscription box",
        "personalization", "product recommendation", "social commerce",
        "live shopping", "fulfillment", "cpg", "private label", "online retail",
    ],
    "Tendencias consumo": [
        # Lenguaje real de prensa, no jerga de consultora — "breakout brand"
        # nunca genera match; "sold out"/"went viral"/"cult following" sí.
        "sold out", "waitlist", "can't keep up with demand", "demand surge",
        "cult following", "cult favorite", "went viral", "viral on tiktok",
        "fastest-growing", "fastest growing", "gains market share",
        "hottest category", "booming category", "new category",
        "gap in the market", "fills a gap", "expands into", "rebrand",
    ],
    "Fintech/Clase media": [
        "fintech", "financial inclusion", "remittance", "savings", "lending",
        "microfinance", "personal finance", "middle class",
    ],
    "Marketplace": ["marketplace"],
    "Tradicional reinventado": [
        "reinventing", "disrupting", "reimagining", "tech-enabled",
        "on-demand", "brick-and-mortar", "legacy industry", "dark store",
        "cashierless", "ghost kitchen", "cloud kitchen", "refurbished",
        "recommerce", "laundry", "car wash", "grocery", "manufacturing",
        "factory", "injection molding", "contract manufacturer",
    ],
    "Industrias CL": [
        "mining", "aquaculture", "agtech", "agriculture", "fishery", "salmon",
    ],
}

# --- Fuentes RSS Tier 1 ---
RSS_FEEDS = {
    # EEUU
    "techcrunch": "https://techcrunch.com/feed/",
    "mit":        "https://www.technologyreview.com/feed/",
    # Europa (ideas ~12-18 meses antes de llegar a LatAm)
    # "sifted": bloqueada desde CI (403)
    "techeu":     "https://tech.eu/feed/",
    # Asia
    "techinasia": "https://feeds.feedburner.com/techinasia",
    # Mercados emergentes / clase media global (tesis: clase media)
    "restofworld": "https://restofworld.org/feed/latest/",
    # Ecommerce / DTC / retail (tesis: ecommerce) — mismo publisher que hrdive
    # y manufacturingdive (Industry Dive), ya probado confiable.
    "modernretail": "https://www.modernretail.co/feed/",
    "retaildive":   "https://www.retaildive.com/feeds/news/",
    # "2pml": eliminada 2026-08 — último post 5 jul, 6+ semanas sin publicar
    # Futuro del trabajo / workforce (tesis: futuro del trabajo)
    "joshbersin": "https://joshbersin.com/feed/",       # analista #1 de HR tech
    "charter":    "https://charterworks.com/feed/",     # periodismo futuro del trabajo
    "hrdive":     "https://www.hrdive.com/feeds/news/", # noticias industria HR
    # Manufactura/industria tradicional (tesis: tradicional reinventado —
    # el hueco real: HN/TechCrunch casi nunca cubren una fábrica de plásticos
    # que cambió de modelo. Mismo publisher que hrdive (Industry Dive).
    "manufacturingdive": "https://www.manufacturingdive.com/feeds/news/",
    # "worklife": muerta — último post dic 2025
    # "wired": eliminada — solo reviews de productos de consumo, sin señal de negocio
}

# Reddit r/SaaS: único subreddit activo sin rate-limit en CI.
# r/startups y r/entrepreneur dan 429 desde GitHub Actions con múltiples calls.
REDDIT_FEEDS = {
    "reddit_saas": "https://www.reddit.com/r/SaaS/top/.rss?t=week&limit=25",
}

# --- Fuentes activas ---
# Product Hunt requiere token (módulo opcional).
ENABLE_PRODUCTHUNT = bool(os.environ.get("PRODUCTHUNT_TOKEN"))
# YC: API comunitaria estática (yc-oss), gratis y sin bloqueo CI — activa por defecto.
ENABLE_YC = os.environ.get("SCOUTING_ENABLE_YC", "true").lower() == "true"

# --- Email (Gmail SMTP) ---
# Mismas credenciales que el Financial Dashboard.
# Generar App Password en: Google Account → Security → 2-Step → App Passwords
GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
EMAIL_TO           = os.environ.get("EMAIL_TO", "matiasmollerv@gmail.com")
