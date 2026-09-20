"""Recolección SIN LLM del Oracle: fuentes preferidas por país × lente.

2026-09-20: el Oracle original solo usaba la búsqueda web de pago, sin decirle
DÓNDE mirar. Acá se invierte: se recolecta gratis (como el scouting semanal) y el
modelo solo lee lo que ya pasó por el filtro.

Cómo se llega a fuentes que no se pueden bajar directo desde CI (Reddit,
Reclame Aqui, Trustpilot, Sifted, e27, reguladores sin RSS): vía Google Noticias
con el operador `site:` — `news.google.com/rss/search?q=(site:dominio) palabras`.
Es un RSS público, sin API key, y devuelve título + fragmento + medio (no el
texto completo: para eso está la etapa de lectura con el modelo).

Tres capas por combinación (país, lente):
  1. abiertas  — consultas temáticas en el idioma del país (amplitud)
  2. curadas   — dominios preferidos del país (prensa, reguladores, gremios) +
                 dominios de quejas globales, filtrados por palabras del lente
  3. pool      — artículos que el scouting semanal ya juntó (data/pool.json)
"""
from __future__ import annotations

import re
import time
import urllib.parse
from datetime import datetime, timezone

import feedparser
import httpx

# país -> (hl, gl, ceid, idioma de las consultas)
EDITIONS: dict[str, tuple[str, str, str, str]] = {
    "CL": ("es-419", "CL", "CL:es-419", "es"), "MX": ("es-419", "MX", "MX:es-419", "es"),
    "PE": ("es-419", "PE", "PE:es-419", "es"), "CO": ("es-419", "CO", "CO:es-419", "es"),
    "AR": ("es-419", "AR", "AR:es-419", "es"), "ES": ("es", "ES", "ES:es", "es"),
    "BR": ("pt-BR", "BR", "BR:pt-419", "pt"),
    "US": ("en-US", "US", "US:en", "en"), "UK": ("en-GB", "GB", "GB:en", "en"),
    "AU": ("en-AU", "AU", "AU:en", "en"), "IN": ("en-IN", "IN", "IN:en", "en"),
    "SG": ("en-SG", "SG", "SG:en", "en"), "IL": ("en-IL", "IL", "IL:en", "en"),
    # Sin edición propia útil en inglés: se consulta la edición US con `site:` local.
    "CN": ("en-US", "US", "US:en", "en"), "DE": ("en-US", "US", "US:en", "en"),
    "NL": ("en-US", "US", "US:en", "en"), "KR": ("en-US", "US", "US:en", "en"),
}

# Dominios de quejas/opinión abiertos: aplican a todo país (señal "queja").
COMPLAINT_SITES = ["reddit.com", "trustpilot.com"]

# Verificados 2026-09-20 con Google Noticias (site: devolvió resultados en 90d).
# "general" = prensa de negocios/tecnología del país (todos los lentes);
# el resto = reguladores, gremios y prensa sectorial de ese lente.
SITES: dict[str, dict[str, list[str]]] = {
    "CL": {"general": ["df.cl", "latercera.com", "ex-ante.cl", "biobiochile.cl", "fayerwayer.com",
                       "pauta.cl", "elmostrador.cl", "emol.com"],
           "fintech": ["cmfchile.cl", "bcentral.cl", "sernac.cl"],
           "futuro_trabajo": ["dt.gob.cl"], "ops_b2b": ["sofofa.cl", "corfo.cl"],
           "comercio": ["sernac.cl"], "servicios_hogar": ["sernac.cl"],
           "exportadoras": ["odepa.gob.cl", "asoex.cl", "salmonchile.cl", "sonami.cl", "chilealimentos.com"],
           "inmobiliario": ["portalinmobiliario.com", "cchc.cl"]},
    "BR": {"general": ["valor.globo.com", "exame.com", "neofeed.com.br", "startups.com.br",
                       "infomoney.com.br", "canaltech.com.br", "pipelinevalor.globo.com", "folha.uol.com.br"],
           "fintech": ["bcb.gov.br", "febraban.org.br"], "ops_b2b": ["sebrae.com.br"],
           "comercio": ["reclameaqui.com.br", "mobiletime.com.br"], "servicios_hogar": ["reclameaqui.com.br"],
           "exportadoras": ["sebrae.com.br"]},
    "MX": {"general": ["expansion.mx", "elfinanciero.com.mx", "eleconomista.com.mx", "forbes.com.mx", "contxto.com"],
           "fintech": ["condusef.gob.mx", "cnbv.gob.mx", "banxico.org.mx", "fintechmexico.org"],
           "comercio": ["profeco.gob.mx"], "servicios_hogar": ["profeco.gob.mx"]},
    "US": {"general": ["axios.com", "fastcompany.com", "hbr.org", "crunchbase.com", "businessinsider.com",
                       "fortune.com", "techcrunch.com", "forbes.com"]},
    "ES": {"general": ["expansion.com", "cincodias.elpais.com", "xataka.com", "elreferente.es",
                       "eleconomista.es", "elespanol.com"],
           "fintech": ["cnmv.es", "bde.es"], "inmobiliario": ["idealista.com"]},
    "UK": {"general": ["ft.com", "cityam.com", "uktech.news", "sifted.eu", "theguardian.com", "bbc.com",
                       "telegraph.co.uk"],
           "fintech": ["fca.org.uk"], "comercio": ["which.co.uk"], "servicios_hogar": ["which.co.uk"],
           "inmobiliario": ["propertyweek.com"]},
    "PE": {"general": ["gestion.pe", "semanaeconomica.com", "elcomercio.pe", "larepublica.pe"],
           "fintech": ["sbs.gob.pe"], "comercio": ["indecopi.gob.pe"]},
    "CO": {"general": ["larepublica.co", "portafolio.co", "valoraanalitik.com", "eltiempo.com",
                       "colombiafintech.co"],
           "fintech": ["superfinanciera.gov.co"]},
    "AR": {"general": ["ambito.com", "cronista.com", "infobae.com", "lanacion.com.ar", "iproup.com", "clarin.com"]},
    "DE": {"general": ["handelsblatt.com", "t3n.de", "heise.de", "wiwo.de"], "fintech": ["bafin.de"]},
    "NL": {"general": ["fd.nl", "nu.nl", "emerce.nl", "nltimes.nl", "dutchnews.nl"]},
    "AU": {"general": ["afr.com", "smartcompany.com.au", "startupdaily.net", "itnews.com.au", "abc.net.au"]},
    "IN": {"general": ["economictimes.indiatimes.com", "inc42.com", "yourstory.com", "entrackr.com",
                       "livemint.com", "business-standard.com"],
           "fintech": ["rbi.org.in"]},
    "CN": {"general": ["technode.com", "scmp.com", "caixinglobal.com", "pandaily.com", "36kr.com",
                       "sixthtone.com", "chinadaily.com.cn"]},
    "IL": {"general": ["calcalistech.com", "globes.co.il", "timesofisrael.com", "jpost.com"]},
    "KR": {"general": ["koreaherald.com", "koreatimes.co.kr", "thelec.net"]},
    "SG": {"general": ["businesstimes.com.sg", "straitstimes.com", "dealstreetasia.com",
                       "channelnewsasia.com", "techinasia.com", "e27.co"]},
}

# Consultas abiertas (amplitud) por lente e idioma. Verbos y sustantivos concretos,
# no el nombre del lente: buscan la SEÑAL (queja, brecha, regulación, oferta).
QUERIES: dict[str, dict[str, list[str]]] = {
    "futuro_trabajo": {
        "es": ['pymes agentes de IA tareas administrativas', 'equipos remotos gestión productividad herramientas',
               'freelancers independientes plataformas trabajo', 'automatización trabajo administrativo empresas'],
        "pt": ['pequenas empresas agentes de IA tarefas administrativas', 'equipes remotas gestão produtividade ferramentas',
               'freelancers autônomos plataformas trabalho', 'automação trabalho administrativo empresas'],
        "en": ['small business AI agents administrative tasks', 'remote teams management productivity tools',
               'freelancers platforms independent work', 'automation back-office work companies']},
    "adopcion_ia": {
        "es": ['adopción inteligencia artificial empresas encuesta', 'empresas no usan inteligencia artificial barreras',
               'capacitación inteligencia artificial ejecutivos', 'regulación inteligencia artificial empresas'],
        "pt": ['adoção inteligência artificial empresas pesquisa', 'empresas não usam inteligência artificial barreiras',
               'capacitação inteligência artificial executivos', 'regulação inteligência artificial empresas'],
        "en": ['AI adoption companies survey', 'companies not using AI barriers', 'AI training executives upskilling',
               'AI regulation compliance companies']},
    "ia_real": {
        "es": ['inteligencia artificial cámaras seguridad laboral planta', 'visión computacional control de calidad',
               'IA coaching vendedores tiendas', 'sensores mermas retail operación'],
        "pt": ['inteligência artificial câmeras segurança do trabalho fábrica', 'visão computacional controle de qualidade',
               'IA treinamento vendedores lojas', 'sensores perdas varejo operação'],
        "en": ['computer vision workplace safety factory', 'AI quality control manufacturing cameras',
               'AI sales coaching audio stores', 'sensors shrinkage retail operations AI']},
    "fintech": {
        "es": ['crédito pymes fintech', 'inclusión financiera bancarización', 'open finance regulación pagos',
               'seguros insurtech penetración', 'reclamos bancos consumidores'],
        "pt": ['crédito pequenas empresas fintech', 'inclusão financeira bancarização', 'open finance regulação pagamentos',
               'seguros insurtech penetração', 'reclamações bancos consumidores'],
        "en": ['SME lending fintech', 'financial inclusion underbanked', 'open banking regulation payments',
               'insurtech insurance gap', 'bank complaints consumers']},
    "salud_bienestar": {
        "es": ['longevidad bienestar startups', 'salud mental acceso aplicaciones', 'estética medicina regenerativa clínicas',
               'suplementos regulación sanitaria'],
        "pt": ['longevidade bem-estar startups', 'saúde mental acesso aplicativos', 'estética medicina regenerativa clínicas',
               'suplementos regulação sanitária'],
        "en": ['longevity wellness startups', 'mental health access apps', 'aesthetics regenerative medicine clinics',
               'supplements regulation health']},
    "ops_b2b": {
        "es": ['pymes facturación cobranza pago a 60 días', 'ERP CRM pymes digitalización planillas',
               'logística última milla costos empresas', 'compras B2B proveedores plataforma'],
        "pt": ['pequenas empresas faturamento cobrança pagamento 60 dias', 'ERP CRM pequenas empresas digitalização planilhas',
               'logística última milha custos empresas', 'compras B2B fornecedores plataforma'],
        "en": ['SMB invoicing collections late payments', 'ERP CRM small business spreadsheets digitization',
               'last mile logistics costs companies', 'B2B procurement suppliers platform']},
    "comercio": {
        "es": ['vendedores marketplace comisiones quejas', 'ecommerce devoluciones logística',
               'categorías de consumo en alza ventas online', 'comercios sin presencia digital'],
        "pt": ['vendedores marketplace comissões reclamações', 'ecommerce devoluções logística',
               'categorias de consumo em alta vendas online', 'comércios sem presença digital'],
        "en": ['marketplace sellers fees complaints', 'ecommerce returns logistics',
               'consumer categories surging online sales', 'small retailers no online presence']},
    "contenido": {
        "es": ['creadores de contenido monetización', 'marcas contenido inteligencia artificial marketing',
               'influencers agencias sponsors', 'employer branding contenido empresas'],
        "pt": ['criadores de conteúdo monetização', 'marcas conteúdo inteligência artificial marketing',
               'influenciadores agências patrocinadores', 'employer branding conteúdo empresas'],
        "en": ['creator economy monetization', 'brands AI content marketing at scale',
               'influencer agencies sponsorship', 'employer branding content companies']},
    "exportadoras": {
        "es": ['exportadores rechazos normativa mercado destino', 'trazabilidad exportación fruta agro',
               'minería pesca acuicultura tecnología eficiencia', 'certificación exportaciones barreras'],
        "pt": ['exportadores rejeições normas mercado destino', 'rastreabilidade exportação frutas agro',
               'mineração pesca aquicultura tecnologia eficiência', 'certificação exportações barreiras'],
        "en": ['exporters rejections import regulations', 'traceability food exports agriculture',
               'mining fishing aquaculture technology efficiency', 'export certification barriers']},
    "inmobiliario": {
        "es": ['arriendo problemas inmobiliarias', 'déficit habitacional vivienda regulación',
               'construcción modular prefabricada', 'proptech fraccionamiento propiedades'],
        "pt": ['aluguel problemas imobiliárias', 'déficit habitacional moradia regulação',
               'construção modular pré-fabricada', 'proptech fracionamento imóveis'],
        "en": ['rental problems landlords agents', 'housing shortage regulation',
               'modular prefab construction', 'proptech fractional property ownership']},
    "servicios_hogar": {
        "es": ['servicios del hogar plataforma confianza', 'cuidado adultos mayores servicios domicilio',
               'informalidad reparaciones WhatsApp', 'plataformas limpieza mudanzas'],
        "pt": ['serviços domésticos plataforma confiança', 'cuidado idosos serviços domicílio',
               'informalidade reparos WhatsApp', 'plataformas limpeza mudanças'],
        "en": ['home services platform trust', 'elder care home services',
               'informal repair services WhatsApp', 'cleaning moving platforms']},
}

# Palabras del lente para filtrar las fuentes curadas (que publican de todo).
KEYWORDS: dict[str, dict[str, list[str]]] = {
    "futuro_trabajo": {"es": ['"equipos remotos"', '"trabajo remoto"', '"agentes de IA"', 'freelancers', 'pymes', 'automatización', 'productividad'],
                       "pt": ['"equipes remotas"', '"trabalho remoto"', '"agentes de IA"', 'freelancers', 'automação', 'produtividade'],
                       "en": ['"remote work"', '"AI agents"', 'freelancers', 'automation', 'productivity', '"small business"']},
    "adopcion_ia": {"es": ['"inteligencia artificial"', 'IA', 'adopción', 'empresas'], "pt": ['"inteligência artificial"', 'IA', 'adoção', 'empresas'],
                    "en": ['"artificial intelligence"', 'AI', 'adoption', 'enterprise']},
    "ia_real": {"es": ['"visión computacional"', 'cámaras', 'sensores', '"control de calidad"', 'wearables'],
                "pt": ['"visão computacional"', 'câmeras', 'sensores', '"controle de qualidade"', 'wearables'],
                "en": ['"computer vision"', 'cameras', 'sensors', '"quality control"', 'wearables']},
    "fintech": {"es": ['fintech', 'crédito', 'pagos', 'seguros', 'bancos', 'inclusión'], "pt": ['fintech', 'crédito', 'pagamentos', 'seguros', 'bancos', 'inclusão'],
                "en": ['fintech', 'lending', 'payments', 'insurance', 'banking', 'inclusion']},
    "salud_bienestar": {"es": ['bienestar', 'longevidad', '"salud mental"', 'estética', 'suplementos', 'clínicas'],
                        "pt": ['bem-estar', 'longevidade', '"saúde mental"', 'estética', 'suplementos', 'clínicas'],
                        "en": ['wellness', 'longevity', '"mental health"', 'aesthetics', 'supplements', 'clinics']},
    "ops_b2b": {"es": ['pymes', 'facturación', 'cobranza', 'ERP', 'CRM', 'logística', 'compras'], "pt": ['pequenas empresas', 'faturamento', 'cobrança', 'ERP', 'CRM', 'logística', 'compras'],
                "en": ['SMB', 'invoicing', 'collections', 'ERP', 'CRM', 'logistics', 'procurement']},
    "comercio": {"es": ['marketplace', 'ecommerce', 'vendedores', 'comercio', 'devoluciones'], "pt": ['marketplace', 'ecommerce', 'vendedores', 'comércio', 'devoluções'],
                 "en": ['marketplace', 'ecommerce', 'sellers', 'retail', 'returns']},
    "contenido": {"es": ['creadores', 'influencers', 'contenido', 'marcas', 'monetización'], "pt": ['criadores', 'influenciadores', 'conteúdo', 'marcas', 'monetização'],
                  "en": ['creators', 'influencers', 'content', 'brands', 'monetization']},
    "exportadoras": {"es": ['exportaciones', 'exportadores', 'trazabilidad', 'agro', 'minería', 'acuicultura'], "pt": ['exportações', 'exportadores', 'rastreabilidade', 'agro', 'mineração', 'aquicultura'],
                     "en": ['exports', 'exporters', 'traceability', 'agriculture', 'mining', 'aquaculture']},
    "inmobiliario": {"es": ['arriendo', 'vivienda', 'inmobiliaria', 'construcción', 'proptech'], "pt": ['aluguel', 'moradia', 'imobiliária', 'construção', 'proptech'],
                     "en": ['rental', 'housing', 'real estate', 'construction', 'proptech']},
    "servicios_hogar": {"es": ['hogar', 'limpieza', 'reparaciones', 'cuidado', 'servicios'], "pt": ['casa', 'limpeza', 'reparos', 'cuidado', 'serviços'],
                        "en": ['home services', 'cleaning', 'repairs', 'caregiving', 'household']},
}

DELAY = 0.35        # segundos entre consultas (Google Noticias tolera ~3/s)
MAX_SITES_PER_QUERY = 6
_UA = {"User-Agent": "Mozilla/5.0 (compatible; scouting-agent/1.0)"}


def _rss_url(q: str, cc: str) -> str:
    hl, gl, ceid, _ = EDITIONS[cc]
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": hl, "gl": gl, "ceid": ceid})


def _get(url: str, client: httpx.Client, tries: int = 3) -> str:
    for i in range(tries):
        try:
            r = client.get(url, timeout=25)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 503):
                time.sleep(2 * (i + 1))
                continue
            return ""
        except httpx.HTTPError:
            time.sleep(1 + i)
    return ""


def _clean_title(title: str, source: str) -> str:
    suffix = f" - {source}"
    return title[: -len(suffix)] if source and title.endswith(suffix) else title


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _entries(xml: str, via: str) -> list[dict]:
    out = []
    for e in feedparser.parse(xml).entries:
        src = (e.get("source") or {}).get("title", "") or ""
        out.append({
            "title": _clean_title(e.get("title", "") or "", src), "source": src,
            "domain": urllib.parse.urlparse((e.get("source") or {}).get("href", "") or "").netloc.removeprefix("www."),
            "url": e.get("link", "") or "", "snippet": _strip(e.get("summary", ""))[:300],
            "published": e.get("published", "") or "", "via": via,
        })
    return out


def queries_for(cc: str, lens_key: str, days: int = 30) -> list[tuple[str, str]]:
    """[(via, consulta)] de las capas 'abiertas' y 'curadas' para el par."""
    lang = EDITIONS[cc][3]
    qs = [("abierta", f"{q} when:{days}d") for q in QUERIES[lens_key][lang]]
    sites = SITES.get(cc, {})
    curated = list(dict.fromkeys(sites.get("general", []) + sites.get(lens_key, [])
                                 + COMPLAINT_SITES + (["reclameaqui.com.br"] if cc == "BR" else [])))
    kw = " OR ".join(KEYWORDS[lens_key][lang])
    for i in range(0, len(curated), MAX_SITES_PER_QUERY):
        chunk = curated[i:i + MAX_SITES_PER_QUERY]
        qs.append(("curada", f"({' OR '.join('site:' + d for d in chunk)}) ({kw}) when:{days}d"))
    return qs


def fetch_pair(cc: str, lens_key: str, client: httpx.Client, days: int = 30,
               cache: dict[str, list[dict]] | None = None) -> list[dict]:
    """Items únicos (por título) del par, con su capa de origen. Sin LLM, costo $0."""
    cache = cache if cache is not None else {}
    seen: set[str] = set()
    out: list[dict] = []
    for via, q in queries_for(cc, lens_key, days):
        url = _rss_url(q, cc)
        if url not in cache:
            cache[url] = _entries(_get(url, client), via)
            time.sleep(DELAY)
        for it in cache[url]:
            key = re.sub(r"\W+", "", it["title"].lower())[:80]
            if key and key not in seen:
                seen.add(key)
                out.append(it)
    return out


def pool_items(lens_key: str, days: int = 10) -> list[dict]:
    """Artículos que el scouting semanal ya recolectó (gratis), filtrados por las
    palabras EN del lente. Sin país: complementan, no reemplazan la búsqueda local."""
    from ..pipeline.pool import load_pool_items
    kws = [k.strip('"').lower() for k in KEYWORDS[lens_key]["en"]]
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    out = []
    for it in load_pool_items():
        if it.published_at and it.published_at.timestamp() < cutoff:
            continue
        hay = f"{it.title} {it.text}".lower()
        if any(k in hay for k in kws):
            out.append({"title": it.title, "source": it.source, "domain": "", "url": it.url,
                        "snippet": it.text[:300], "published": "", "via": "pool"})
    return out
