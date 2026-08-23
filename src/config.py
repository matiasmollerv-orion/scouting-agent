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

# Fuentes que publican con MENOS frecuencia que semanal — con LOOKBACK_DAYS=7
# quedan casi siempre en 0 items aunque estén vivas (no es lo mismo que
# "muerta": geekestate publica cada ~2 semanas, no cada 2+ años como
# andrewchen, que se sacó de RSS_FEEDS por esa razón). El pool diario poda
# por fecha de DESCUBRIMIENTO, no de publicación — con ventana más ancha el
# job diario igual las encuentra a tiempo.
LOOKBACK_OVERRIDES = {
    "geekestate": 25,
    "creatoreconomy": 25,
}

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
# El triage es MUY barato (~$0.0003/item) — subir esto no mueve el costo
# real de forma significativa (30->100 ≈ +$0.02/semana), pero hace que
# muchísimo más contenido tenga al menos un score visible en el dashboard
# en vez de perderse en el prefiltro sin dejar rastro (feedback 2026-08:
# "quiero poder ver el artículo aunque no se profundice, y decidir yo").
# TOP_DEEP (el análisis caro) NO cambia — sigue siendo 8, el costo real
# de la corrida semanal no se mueve.
#
# 2026-08: se sacó el filtro DURO de keywords en prefilter.py — ahora TODO
# lo deduplicado/no-visto compite por cupo (round-robin por fuente), no solo
# lo que matchea una palabra. El tope real de fill natural es ~14 fuentes ×
# su cupo (hackernews=10, resto=7 default) ≈ 100-110 — 150 da margen para
# no cortar antes de ese fill natural.
# Overridable por env para mini-runs reales (ej: SCOUTING_MAX_CANDIDATES=3).
MAX_CANDIDATES = int(os.environ.get("SCOUTING_MAX_CANDIDATES", "150"))

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
    # Tesis: ecommerce — IA y herramientas cara al cliente
    "product recommendation", "personalization engine", "personalized shopping",
    "dynamic pricing", "visual search", "virtual try-on", "try before you buy",
    "conversational commerce", "ai shopping", "shopping assistant",
    "product discovery", "search and discovery",
    # Tesis: ecommerce — B2B para empresas que venden online, EL PRINCIPIO
    # amplio (ayudar a vender más/gastar menos/operar más liviano), no una
    # lista cerrada de ejemplos puntuales:
    "inventory management", "demand forecasting", "stock optimization",
    "ai agent for ecommerce", "ai agent for merchants", "ai copilot for sellers",
    "customer service automation", "catalog management", "returns automation",
    "merchant financing", "revenue-based financing", "merchant cash advance",
    "seller financing", "working capital for sellers", "ecommerce operations",
    "3pl", "third-party logistics", "shipping software", "shipping rates",
    "packaging startup", "sustainable packaging", "multi-channel selling",
    "marketplace management software", "channel management", "reviews platform",
    "user-generated content platform", "loyalty program software",
    "subscription management software", "seller analytics", "ecommerce analytics",
    "sales tax compliance", "merchant compliance", "ecommerce ads platform",
    "retail media", "affiliate marketing platform", "influencer marketing platform",
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
    # Tesis: bienestar financiero — hábitos B2C + acceso al mercado
    # financiero B2B/infra (personas Y empresas). Convicción personal del
    # fundador (2026-08): sus propios hábitos de inversión recurrente le
    # cambiaron la trayectoria financiera.
    "personal finance app", "budgeting app", "expense tracker",
    "spending habits", "micro-spending", "subscription tracker",
    "round-up investing", "round up savings", "automated savings",
    "automated investing", "recurring investment", "robo-advisor",
    "robo advisor", "investment app", "wealth app", "wealthtech",
    "financial literacy", "financial wellness", "money management app",
    "embedded finance", "banking the unbanked", "unbanked", "underbanked",
    "credit access", "alternative credit", "credit scoring",
    "working capital", "small business lending", "sme lending",
    "invoice financing",
    # Bienestar financiero: gasto corporativo con control (elegido, no
    # neobancos/insurtech/cripto/regtech/trading — decisión explícita)
    "spend management", "corporate card", "corporate expense",
    "expense management software", "corporate spending",
    # Bienestar financiero: inversión inmobiliaria accesible (elegido)
    "fractional real estate", "real estate investing app",
    "proptech investing", "real estate crowdfunding", "mortgage tech",
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
    # Ecommerce dividido en 3 sub-temas (antes un solo bucket "Ecommerce/DTC"
    # muy amplio para ser accionable — feedback: "si me hablaras de una nueva
    # tecnología/solución/modelo de negocio en la industria, sería power").
    "Ecommerce: herramientas B2B": [
        "personalization", "product recommendation", "dynamic pricing",
        "virtual try-on", "conversational commerce", "checkout",
        "inventory management", "demand forecasting", "ai agent for ecommerce",
        "ai agent for merchants", "customer service automation",
        "merchant financing", "revenue-based financing", "3pl",
        "shipping software", "multi-channel selling", "seller analytics",
        "retail media", "ecommerce ads",
    ],
    "Ecommerce: tendencias consumo": [
        # Lenguaje real de prensa, no jerga de consultora — "breakout brand"
        # nunca genera match; "sold out"/"went viral"/"cult following" sí.
        "sold out", "waitlist", "can't keep up with demand", "demand surge",
        "cult following", "cult favorite", "went viral", "viral on tiktok",
        "fastest-growing", "fastest growing", "gains market share",
        "hottest category", "booming category", "new category",
        "gap in the market", "fills a gap",
    ],
    "Ecommerce: marcas DTC maduras": [
        "new product line", "expands into", "extends its", "line extension",
        "expanding internationally", "loyal customers", "rebrand",
        "following its customers", "brand extension",
    ],
    "Fintech/Clase media": [
        "fintech", "financial inclusion", "remittance", "savings", "lending",
        "microfinance", "personal finance", "middle class",
    ],
    "Bienestar financiero": [
        # Lenguaje amplio de prensa fintech real, no solo jerga de producto —
        # "Bienestar financiero" quedó en 0 semanas seguidas con las keywords
        # viejas mientras "Fintech/Clase media" mostraba señal sana (mismo
        # contenido, bucket mal calibrado, no falta de señal real).
        "fintech raises", "digital bank", "neobank", "lending circle",
        "group lending", "peer lending", "savings app", "investing app",
        "budgeting app", "expense tracker", "spending habits",
        "round-up investing", "automated savings", "automated investing",
        "robo-advisor", "financial literacy", "financial wellness",
        "embedded finance", "credit access", "working capital",
        "spend management", "corporate card", "fractional real estate",
        "real estate investing app", "mortgage tech", "buy now pay later",
        "credit score", "microloans",
    ],
    "Inmobiliario": [
        "proptech", "real estate", "co-living", "co-working", "build-to-rent",
        "property management software", "modular construction",
        "prefabricated", "3d-printed building", "fractional real estate",
        "ibuying", "tokenized real estate",
    ],
    "Creadores de contenido": [
        "creator economy", "influencer marketing", "content creator",
        "youtuber", "brand deal", "sponsorship platform", "creator monetization",
        "ugc platform", "creator commerce",
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
    # Industrias chilenas: minería, salmonicultura/acuicultura, agro (tesis:
    # industrias CL) — 2026-08: prensa gringa nunca cubre esto, hueco real.
    # Verificadas con contenido fresco y real, no solo HTTP 200:
    "aqua":       "https://www.aqua.cl/feed/",         # salmonicultura/acuicultura
    "mch":        "https://www.mch.cl/feed/",          # Minería Chilena
    "redagricola": "https://redagricola.com/feed/",     # agro/fruticultura
    # Descartadas: salmonexpert.cl y mundoacuicola.cl (404, sin feed real),
    # portalminero.com (feed válido pero solo 1 item, muy bajo volumen),
    # emol.com/df.cl (sin RSS real, redirigen a portada genérica),
    # biobiochile (404 en las rutas de feed probadas).
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
    # Retail/restaurantes tradicionales reinventados (tesis: tradicional
    # reinventado) — mismo hueco: manufacturingdive cubre fábricas, pero no
    # "supermercado sin cajas" ni "cadena de comida rápida con nuevo modelo
    # de delivery". grocerydive es hermana de retaildive/modernretail
    # (Industry Dive), mismo patrón probado. Descartadas: chainstoreage.com
    # y drugstorenews.com (403, bloquean requests automatizados),
    # restaurantbusinessonline.com (feed responde pero 0 items reales).
    "grocerydive": "https://www.grocerydive.com/feeds/news/",
    "nrn":         "https://www.nrn.com/rss.xml",       # Nation's Restaurant News
    # Bienestar financiero / fintech (tesis: bienestar financiero) — el
    # mismo hueco que tenía ecommerce antes de modernretail: prensa tech
    # general cubre rondas, no historias de producto fintech.
    "finextra":    "https://www.finextra.com/rss/headlines.aspx",
    "tearsheet":   "https://tearsheet.co/feed/",       # análisis de fondo, no solo noticias
    "fintechtimes": "https://thefintechtimes.com/feed/",
    # Inmobiliario/proptech (tesis: inmobiliario)
    "geekestate":  "https://geekestateblog.com/feed/", # ex-Zillow, ángulo práctico
    # Creadores de contenido (tesis: creadores de contenido)
    "creatoreconomy": "https://thecreatoreconomy.com/rss.xml",
    # Wellness/estética (tesis: wellness) — hermana de modernretail, mismo
    # dueño (Digiday Media), mismo patrón que ya nos funciona. wellandgood
    # y mobihealthnews evaluadas y descartadas: la primera fue absorbida
    # por theskimm.com (ya no existe sola), la segunda bloquea requests
    # automatizados (403) aunque con el User-Agent del pipeline.
    "glossy":   "https://www.glossy.co/feed/",
    "statnews": "https://www.statnews.com/feed/",
    # Marketplace (tesis: marketplace): andrewchen.com evaluado y descartado
    # como fuente automatizada — feed responde bien pero último post real es
    # de feb 2024, más de 2 años sin publicar. No es "muerta" (sigue online),
    # simplemente no publica con cadencia útil para un pipeline automatizado.
    # Sigue siendo buena LECTURA manual, solo no aporta al fetch semanal.
    # IA ejecutivos (tesis: IA ejecutivos) — estrategia tech/negocio, no
    # solo AI news genérico
    "stratechery": "https://stratechery.com/feed/",
    # B2C servicios (tesis: b2c servicios) — categoría difícil de cubrir
    # porque casi todo trade press es de producto/software, no de servicio
    # puro. Skift es prensa seria de industria de viajes/hospitalidad —
    # servicio recurrente/por uso que paga el consumidor final. Descartadas:
    # therobinreport.com (válida pero redundante con retaildive, mismo
    # ángulo retail), fittinsider.com (no resuelve DNS), blooloop.com
    # (nicho muy angosto — solo atracciones/parques temáticos), thehustle.co
    # (403, y de todos modos suele llegar ya vía brain-inbox del usuario).
    "skift": "https://skift.com/feed/",
    # "worklife": muerta — último post dic 2025
    # "wired": eliminada — solo reviews de productos de consumo, sin señal de negocio
    # "credaily" (CRE Daily): descartada — feed responde 200 pero 0 items reales
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
