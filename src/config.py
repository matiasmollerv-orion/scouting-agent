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
# 20 candidatos × ~400 tokens ≈ 8000 tokens — cómodo bajo límite de 20k.
MAX_CANDIDATES = 20

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
