from __future__ import annotations

import os

# --- Modelo ---
MODEL = os.environ.get("SCOUTING_MODEL", "claude-haiku-4-5")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# --- Gate de scoring ---
MIN_OBJETIVO = int(os.environ.get("SCOUTING_MIN_OBJETIVO", "24"))  # sobre 40
MAX_IDEAS = 5

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

# Cantidad máxima de candidatos que llegan a Claude (control de costo).
# Subido a 50 para absorber las nuevas fuentes sin aplastar Reddit/newsletters.
MAX_CANDIDATES = 50

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
    # Tesis: wellness / longevidad / biohacking
    "wellness", "longevity", "biohacking", "supplement", "wearable",
    "health coach", "mental health", "gut health", "sleep",
    # Tesis: ecommerce / DTC / productos innovadores
    "dtc", "direct-to-consumer", "ecommerce", "shopify", "consumer brand",
    # Tesis: servicios para hogares
    "home services", "household", "home management", "cleaning service",
    # Tesis: grandes industrias chilenas
    "agtech", "mining software", "aquaculture", "precision agriculture",
    "farm management", "fishery", "commodity",
]

# --- Fuentes RSS Tier 1 ---
# Medios tech generales
RSS_FEEDS = {
    "techcrunch": "https://techcrunch.com/feed/",
    "wired": "https://www.wired.com/feed/rss",
    "mit": "https://www.technologyreview.com/feed/",
    # Asia
    "techinasia": "https://feeds.feedburner.com/techinasia",
    # VC / newsletters
    "a16z": "https://a16z.substack.com/feed",
}

# Reddit: feeds públicos top/semana. Requieren User-Agent — se pasan
# en main.py al instanciar RSSFeed con extra_headers.
REDDIT_FEEDS = {
    "reddit_saas":        "https://www.reddit.com/r/SaaS/top/.rss?t=week&limit=25",
    "reddit_startups":    "https://www.reddit.com/r/startups/top/.rss?t=week&limit=25",
    "reddit_entrepreneur":"https://www.reddit.com/r/entrepreneur/top/.rss?t=week&limit=25",
}

# --- Fuentes activas ---
# Product Hunt y YC arrancan apagadas (módulos opcionales).
ENABLE_PRODUCTHUNT = bool(os.environ.get("PRODUCTHUNT_TOKEN"))
ENABLE_YC = os.environ.get("SCOUTING_ENABLE_YC", "false").lower() == "true"
