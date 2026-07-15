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
# Cuántos pasan del triage al análisis profundo. Overridable por env para
# mini-runs reales baratos (ej: SCOUTING_TOP_DEEP=2 ≈ $0.01 total).
TOP_DEEP = int(os.environ.get("SCOUTING_TOP_DEEP", "8"))

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
    # Tesis: futuro del trabajo / planillas grandes
    "future of work", "hr tech", "people analytics", "headcount",
    "workforce planning", "performance review", "performance management",
    "employee onboarding", "shift scheduling", "staffing", "payroll",
    "labor management", "digital worker", "ai coworker", "ai employee",
    "ai agents for work", "org design", "employee engagement",
    # Tesis: wellness / longevidad / biohacking
    "wellness", "longevity", "biohacking", "supplement", "wearable",
    "health coach", "mental health", "gut health", "sleep",
    # Tesis: ecommerce / DTC / productos innovadores
    "dtc", "direct-to-consumer", "ecommerce", "shopify", "consumer brand",
    "subscription box", "cpg", "consumer packaged goods", "private label",
    # Tesis: ecommerce — IA y herramientas que hacen tiendas más eficientes
    "product recommendation", "personalization engine", "dynamic pricing",
    "visual search", "virtual try-on", "conversational commerce",
    "ai shopping", "product discovery",
    # Tesis: ecommerce — señales de categorías de consumo explotando
    "fastest growing", "breakout brand", "emerging category", "consumer trend",
    "viral brand", "trending product", "category creator",
    # Tesis: ecommerce — infraestructura y canales nuevos
    "social commerce", "live shopping", "creator commerce",
    "fulfillment", "returns management", "cross-border ecommerce",
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
        "ecommerce", "dtc", "direct-to-consumer", "shopify", "checkout",
        "consumer brand", "retail tech", "last mile", "subscription box",
        "personalization", "product recommendation", "social commerce",
        "live shopping", "fulfillment", "cpg", "private label",
    ],
    "Tendencias consumo": [
        "consumer trend", "breakout brand", "fastest growing", "viral brand",
        "emerging category", "category creator", "trending product",
        "consumer behavior", "subscription box", "private label",
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
        "recommerce", "laundry", "car wash", "grocery",
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
    # Ecommerce / DTC / retail (tesis: ecommerce)
    "modernretail": "https://www.modernretail.co/feed/",
    "2pml":         "https://2pml.com/feed/",            # análisis DTC/brands/ecommerce
    # Futuro del trabajo / workforce (tesis: futuro del trabajo)
    "joshbersin": "https://joshbersin.com/feed/",       # analista #1 de HR tech
    "charter":    "https://charterworks.com/feed/",     # periodismo futuro del trabajo
    "hrdive":     "https://www.hrdive.com/feeds/news/", # noticias industria HR
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
