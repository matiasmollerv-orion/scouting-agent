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
    # Sin edición propia útil: se consulta la edición US con `site:` local (prensa en inglés).
    "CN": ("en-US", "US", "US:en", "en"), "KR": ("en-US", "US", "US:en", "en"),
    "DE": ("de", "DE", "DE:de", "de"), "NL": ("nl", "NL", "NL:nl", "nl"),
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
           "inmobiliario": ["portalinmobiliario.com", "cchc.cl"],
           "logistica": ["logistica360chile.cl", "mundomaritimo.cl"]},
    "BR": {"general": ["valor.globo.com", "exame.com", "neofeed.com.br", "startups.com.br",
                       "infomoney.com.br", "canaltech.com.br", "pipelinevalor.globo.com", "folha.uol.com.br"],
           "fintech": ["bcb.gov.br", "febraban.org.br"], "ops_b2b": ["sebrae.com.br"],
           "comercio": ["reclameaqui.com.br", "mobiletime.com.br"], "servicios_hogar": ["reclameaqui.com.br"],
           "exportadoras": ["embrapa.br", "canalrural.com.br", "agrolink.com.br", "portaldoagronegocio.com.br", "apexbrasil.com.br"],
           "inmobiliario": ["vivareal.com.br"],
           "logistica": ["mundologistica.com.br", "ecommercebrasil.com.br", "tecnologistica.com.br", "mercadoeconsumo.com.br"],
           "tradicional": ["revistapegn.globo.com", "mercadoeconsumo.com.br", "sebrae.com.br"]},
    "MX": {"general": ["expansion.mx", "elfinanciero.com.mx", "eleconomista.com.mx", "forbes.com.mx", "contxto.com"],
           "fintech": ["condusef.gob.mx", "cnbv.gob.mx", "banxico.org.mx", "fintechmexico.org"],
           "comercio": ["profeco.gob.mx"], "servicios_hogar": ["profeco.gob.mx"],
           "exportadoras": ["senasica.gob.mx", "economia.gob.mx", "agricultura.gob.mx"],
           "inmobiliario": ["inmuebles24.com", "vivanuncios.com.mx"],
           "logistica": ["t21.com.mx"]},
    "US": {"general": ["axios.com", "fastcompany.com", "hbr.org", "crunchbase.com", "businessinsider.com",
                       "fortune.com", "techcrunch.com", "forbes.com"],
           "exportadoras": ["thepacker.com", "agweb.com", "undercurrentnews.com", "mining.com"],
           "servicios_hogar": ["angi.com", "thumbtack.com", "homeadvisor.com"],
           "tradicional": ["bizjournals.com", "inc.com", "franchisetimes.com", "qsrmagazine.com",
                           "smallbiztrends.com", "chainstoreage.com"],
           "logistica": ["freightwaves.com", "supplychainbrain.com"]},
    "ES": {"general": ["expansion.com", "cincodias.elpais.com", "xataka.com", "elreferente.es",
                       "eleconomista.es", "elespanol.com"],
           "fintech": ["cnmv.es", "bde.es"], "inmobiliario": ["idealista.com"],
           "exportadoras": ["mapa.gob.es", "agroinformacion.com", "icex.es", "fepex.es"],
           "logistica": ["logisticaprofesional.com", "interempresas.net"], "tradicional": ["emprendedores.es"]},
    "UK": {"general": ["ft.com", "cityam.com", "uktech.news", "sifted.eu", "theguardian.com", "bbc.com",
                       "telegraph.co.uk"],
           "fintech": ["fca.org.uk"], "comercio": ["which.co.uk"], "servicios_hogar": ["which.co.uk"],
           "inmobiliario": ["propertyweek.com"], "ia_real": ["therobotreport.com", "computerweekly.com"],
           "ops_b2b": ["computerweekly.com"]},
    "PE": {"general": ["gestion.pe", "semanaeconomica.com", "elcomercio.pe", "larepublica.pe"],
           "fintech": ["sbs.gob.pe"], "comercio": ["indecopi.gob.pe"],
           "exportadoras": ["promperu.gob.pe", "senasa.gob.pe", "agraria.pe", "comexperu.org.pe", "mincetur.gob.pe"]},
    "CO": {"general": ["larepublica.co", "portafolio.co", "valoraanalitik.com", "eltiempo.com",
                       "colombiafintech.co"],
           "fintech": ["superfinanciera.gov.co"],
           "exportadoras": ["ica.gov.co", "agronegocios.co", "dian.gov.co", "minagricultura.gov.co", "procolombia.co"]},
    "AR": {"general": ["ambito.com", "cronista.com", "infobae.com", "lanacion.com.ar", "iproup.com", "clarin.com"],
           "exportadoras": ["senasa.gob.ar", "agrofy.com.ar", "infocampo.com.ar", "bolsadecereales.com"]},
    "DE": {"general": ["handelsblatt.com", "t3n.de", "heise.de", "wiwo.de", "spiegel.de", "zeit.de", "businessinsider.de"],
           "fintech": ["bafin.de"]},
    "NL": {"general": ["fd.nl", "nu.nl", "emerce.nl", "nltimes.nl", "dutchnews.nl"],
           "exportadoras": ["agf.nl", "boerenbusiness.nl", "rijksoverheid.nl"]},
    "AU": {"general": ["afr.com", "smartcompany.com.au", "startupdaily.net", "itnews.com.au", "abc.net.au"],
           "exportadoras": ["farmonline.com.au", "weeklytimesnow.com.au", "agriculture.gov.au"],
           "inmobiliario": ["domain.com.au", "realestate.com.au"]},
    "IN": {"general": ["economictimes.indiatimes.com", "inc42.com", "yourstory.com", "entrackr.com",
                       "livemint.com", "business-standard.com"],
           "fintech": ["rbi.org.in"], "servicios_hogar": ["urbancompany.com"],
           "exportadoras": ["apeda.gov.in", "thehindubusinessline.com", "agriculturepost.com"]},
    "CN": {"general": ["technode.com", "scmp.com", "caixinglobal.com", "pandaily.com", "36kr.com",
                       "sixthtone.com", "chinadaily.com.cn"]},
    "IL": {"general": ["calcalistech.com", "globes.co.il", "timesofisrael.com", "jpost.com"]},
    "KR": {"general": ["koreaherald.com", "koreatimes.co.kr", "thelec.net", "en.yna.co.kr", "biz.chosun.com"]},
    "SG": {"general": ["businesstimes.com.sg", "straitstimes.com", "dealstreetasia.com",
                       "channelnewsasia.com", "techinasia.com", "e27.co"]},
}

# Prensa sectorial GLOBAL en inglés por lente (verificada 2026-09-20): señales de oferta y
# fuerza externa transferibles a cualquier país. Va como capa "global" con palabras en inglés.
GLOBAL_SITES: dict[str, list[str]] = {
    "exportadoras": ["freshplaza.com", "fruitnet.com", "undercurrentnews.com", "mining.com", "thefishsite.com"],
    "ia_real": ["therobotreport.com", "venturebeat.com", "technologyreview.com", "spectrum.ieee.org"],
    "salud_bienestar": ["fiercehealthcare.com", "statnews.com"],
    "inmobiliario": ["constructiondive.com"],
    "logistica": ["freightwaves.com", "logisticsmgmt.com", "supplychainbrain.com", "theloadstar.com",
                  "mmh.com", "supplychaindive.com"],
    "tradicional": ["bizjournals.com", "inc.com", "franchisetimes.com", "qsrmagazine.com",
                    "chainstoreage.com", "smallbiztrends.com"],
}

# Consultas abiertas (amplitud) por lente e idioma. Verbos y sustantivos concretos,
# no el nombre del lente: buscan la SEÑAL (queja, brecha, regulación, oferta).
QUERIES: dict[str, dict[str, list[str]]] = {
    # Consultas CORTAS (2-3 palabras comunes): Google Noticias exige todas las palabras, así que
    # las largas devuelven casi nada (medido 2026-09-20: 4 palabras -> 0-13 items; 2-3 -> 20-70).
    "futuro_trabajo": {
        "es": ['agentes IA pymes', 'equipos remotos productividad', 'freelancers plataformas', 'automatización administrativa empresas', 'trabajo remoto herramientas'],
        "pt": ['agentes IA pequenas empresas', 'equipes remotas produtividade', 'freelancers plataformas', 'automação administrativa empresas', 'trabalho remoto ferramentas'],
        "en": ['AI agents small business', 'remote teams productivity', 'freelancers platforms', 'back-office automation companies', 'remote work tools']},
    "adopcion_ia": {
        "es": ['adopción inteligencia artificial empresas', 'empresas inteligencia artificial encuesta', 'capacitación inteligencia artificial', 'regulación inteligencia artificial'],
        "pt": ['adoção inteligência artificial empresas', 'empresas inteligência artificial pesquisa', 'capacitação inteligência artificial', 'regulação inteligência artificial'],
        "en": ['AI adoption companies', 'companies AI survey', 'AI training executives', 'AI regulation compliance']},
    "ia_real": {
        "es": ['visión computacional planta', 'inteligencia artificial cámaras seguridad', 'IA control de calidad', 'sensores mermas retail'],
        "pt": ['visão computacional fábrica', 'inteligência artificial câmeras segurança', 'IA controle de qualidade', 'sensores perdas varejo'],
        "en": ['computer vision factory', 'AI cameras workplace safety', 'AI quality control', 'sensors retail shrinkage']},
    "fintech": {
        "es": ['crédito pymes', 'inclusión financiera', 'open finance', 'insurtech seguros', 'reclamos bancos'],
        "pt": ['crédito pequenas empresas', 'inclusão financeira', 'open finance', 'insurtech seguros', 'reclamações bancos'],
        "en": ['SME lending', 'financial inclusion', 'open banking', 'insurtech insurance', 'bank complaints']},
    "salud_bienestar": {
        "es": ['longevidad bienestar', 'salud mental aplicaciones', 'medicina estética clínicas', 'suplementos regulación'],
        "pt": ['longevidade bem-estar', 'saúde mental aplicativos', 'medicina estética clínicas', 'suplementos regulação'],
        "en": ['longevity wellness', 'mental health apps', 'aesthetics clinics', 'supplements regulation']},
    "ops_b2b": {
        "es": ['pymes facturación cobranza', 'ERP pymes digitalización', 'compras B2B proveedores'],
        "pt": ['pequenas empresas faturamento cobrança', 'ERP pequenas empresas digitalização', 'compras B2B fornecedores'],
        "en": ['SMB invoicing collections', 'ERP small business', 'B2B procurement suppliers']},
    "comercio": {
        "es": ['vendedores marketplace comisiones', 'ecommerce devoluciones', 'ventas online categorías', 'comercio digitalización pymes'],
        "pt": ['vendedores marketplace comissões', 'ecommerce devoluções', 'vendas online categorias', 'comércio digitalização pequenas empresas'],
        "en": ['marketplace sellers fees', 'ecommerce returns', 'online sales categories', 'small retailers digital']},
    "contenido": {
        "es": ['creadores de contenido', 'influencers monetización', 'marcas contenido IA', 'employer branding'],
        "pt": ['criadores de conteúdo', 'influenciadores monetização', 'marcas conteúdo IA', 'employer branding'],
        "en": ['creator economy', 'influencers monetization', 'brands AI content', 'employer branding']},
    "exportadoras": {
        "es": ['exportadores normativa', 'trazabilidad exportación', 'rechazos exportaciones', 'agroexportación tecnología', 'minería pesca tecnología'],
        "pt": ['exportadores normas', 'rastreabilidade exportação', 'rejeições exportações', 'agroexportação tecnologia', 'mineração pesca tecnologia'],
        "en": ['exporters regulations', 'food traceability', 'export rejections', 'agriculture exports technology', 'mining fishing technology']},
    "inmobiliario": {
        "es": ['arriendo inmobiliarias', 'déficit habitacional', 'construcción modular', 'proptech'],
        "pt": ['aluguel imobiliárias', 'déficit habitacional', 'construção modular', 'proptech'],
        "en": ['rental landlords', 'housing shortage', 'modular construction', 'proptech']},
    "tradicional": {
        "es": ['"pyme del año"', '"empresa familiar" crece locales', 'emprendedor abrió su local', 'franquicia nueva marca',
               'cadena de locales expande', 'lavandería panadería ferretería emprendedor'],
        "pt": ['padaria rede expande unidades', 'lavanderia franquia', 'franquia cresce faturamento',
               'supermercado nova loja expansão', 'empreendedor franquia cresce'],
        "en": ['"small business of the year"', '"opens second location"', '"family-owned" fastest-growing',
               'franchise fastest-growing', '"new concept" store opens', '"car wash" membership', 'laundromat subscription']},
    "logistica": {
        "es": ['bodegaje', 'fulfillment ecommerce', 'última milla', 'centros de distribución', 'logística inversa devoluciones', 'bodegas arriendo'],
        "pt": ['armazém fulfillment', 'última milha', 'centro de distribuição', 'logística reversa', 'ecommerce logística'],
        "en": ['warehouse fulfillment', '3PL', 'last-mile delivery', 'cold storage', 'reverse logistics returns', 'warehouse automation']},
    "servicios_hogar": {
        "es": ['servicios del hogar plataforma', 'cuidado adultos mayores', 'reparaciones WhatsApp', 'limpieza mudanzas plataformas'],
        "pt": ['serviços domésticos plataforma', 'cuidado idosos', 'reparos WhatsApp', 'limpeza mudanças plataformas'],
        "en": ['home services platform', 'elder care', 'home repairs contractors', 'cleaning moving platforms']},
}

QUERIES_LOCAL: dict[str, dict[str, list[str]]] = {
    "de": {
        "futuro_trabajo": ['KI Mittelstand Verwaltung', 'Remote Teams Produktivität', 'Freelancer Plattformen', 'Automatisierung Büroarbeit'],
        "adopcion_ia": ['KI Einführung Unternehmen', 'KI Unternehmen Umfrage', 'KI Weiterbildung', 'KI Regulierung Unternehmen'],
        "ia_real": ['KI Qualitätskontrolle Produktion', 'KI Kameras Arbeitssicherheit', 'KI Sensoren Handel', 'Computer Vision Industrie'],
        "fintech": ['Mittelstand Kredit', 'Fintech Zahlungen', 'Open Banking', 'Insurtech Versicherung', 'Bank Beschwerden'],
        "salud_bienestar": ['Longevity Wellness', 'psychische Gesundheit App', 'Ästhetik Klinik', 'Nahrungsergänzung Regulierung'],
        "ops_b2b": ['Mittelstand Rechnung Zahlungsverzug', 'ERP Mittelstand', 'Logistik letzte Meile', 'B2B Einkauf Plattform'],
        "comercio": ['Marktplatz Händler Gebühren', 'E-Commerce Retouren', 'Onlinehandel Wachstum'],
        "inmobiliario": ['Miete Vermieter Probleme', 'Wohnungsknappheit', 'modulares Bauen', 'Proptech'],
    },
    "nl": {
        "futuro_trabajo": ['AI mkb administratie', 'remote teams productiviteit', 'zzp platforms', 'automatisering kantoorwerk'],
        "adopcion_ia": ['AI adoptie bedrijven', 'AI bedrijven onderzoek', 'AI training', 'AI regelgeving bedrijven'],
        "ia_real": ['AI kwaliteitscontrole productie', 'AI camera veiligheid', 'AI sensoren retail', 'computer vision industrie'],
        "salud_bienestar": ['longevity welzijn', 'geestelijke gezondheid app', 'esthetische kliniek', 'supplementen regelgeving'],
        "ops_b2b": ['mkb facturen betaling', 'ERP mkb', 'logistiek laatste mijl', 'B2B inkoop platform'],
        "exportadoras": ['export regels landbouw', 'traceerbaarheid voedsel', 'exporteurs importregels', 'landbouw technologie export'],
        "inmobiliario": ['huurders verhuurders', 'woningtekort', 'modulair bouwen', 'proptech'],
    },
}
KEYWORDS_LOCAL: dict[str, dict[str, list[str]]] = {
    "de": {"futuro_trabajo": ['Remote-Arbeit', 'KI-Agenten', 'Freelancer', 'Automatisierung', 'Produktivität'],
           "adopcion_ia": ['"künstliche Intelligenz"', 'KI', 'Einführung', 'Unternehmen'],
           "ia_real": ['"Computer Vision"', 'Kameras', 'Sensoren', 'Qualitätskontrolle'],
           "fintech": ['Fintech', 'Kredit', 'Zahlungen', 'Versicherung', 'Bank'],
           "salud_bienestar": ['Wellness', 'Longevity', '"psychische Gesundheit"', 'Ästhetik'],
           "ops_b2b": ['Mittelstand', 'Rechnung', 'ERP', 'CRM', 'Logistik'],
           "comercio": ['Marktplatz', 'E-Commerce', 'Händler', 'Retouren'],
           "inmobiliario": ['Miete', 'Wohnung', 'Immobilien', 'Bau']},
    "nl": {"futuro_trabajo": ['thuiswerken', 'AI-agenten', 'zzp', 'automatisering', 'productiviteit'],
           "adopcion_ia": ['"kunstmatige intelligentie"', 'AI', 'adoptie', 'bedrijven'],
           "ia_real": ['"computer vision"', 'camera', 'sensoren', 'kwaliteitscontrole'],
           "salud_bienestar": ['welzijn', 'longevity', '"geestelijke gezondheid"', 'esthetisch'],
           "ops_b2b": ['mkb', 'factuur', 'ERP', 'CRM', 'logistiek'],
           "exportadoras": ['export', 'exporteurs', 'traceerbaarheid', 'landbouw'],
           "inmobiliario": ['huur', 'woning', 'vastgoed', 'bouw']},
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
                "en": ['"computer vision"', '"machine vision"', 'cameras', 'sensors', '"quality control"', 'wearables', 'robots']},
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
    "tradicional": {"es": ['emprendedor', 'pyme', '"empresa familiar"', 'franquicia', 'locales', 'tienda', 'cadena', 'facturación'],
                    "pt": ['empreendedor', 'pequena empresa', '"empresa familiar"', 'franquia', 'unidades', 'loja', 'rede', 'faturamento'],
                    "en": ['founder', 'family-owned', 'franchise', 'locations', 'store', 'chain', 'revenue', '"small business"']},
    "logistica": {"es": ['bodega', 'fulfillment', '"última milla"', 'logística', 'almacenamiento', 'despacho'],
                  "pt": ['armazém', 'fulfillment', '"última milha"', 'logística', 'armazenagem'],
                  "en": ['warehouse', 'fulfillment', '3PL', 'last-mile', '"cold chain"', 'logistics']},
    "servicios_hogar": {"es": ['hogar', 'limpieza', 'reparaciones', 'cuidado', 'servicios'], "pt": ['casa', 'limpeza', 'reparos', 'cuidado', 'serviços'],
                        "en": ['"home services"', 'cleaning', 'repairs', 'caregiving', 'plumber', 'contractor', '"elder care"', 'nanny']},
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


def lang_terms(cc: str, lens_key: str, kind: str) -> tuple[str, list[str]]:
    """(idioma efectivo, términos) del país para el lente; cae a inglés si no hay traducción."""
    lang = EDITIONS[cc][3]
    local = (QUERIES_LOCAL if kind == "queries" else KEYWORDS_LOCAL).get(lang, {})
    base = QUERIES if kind == "queries" else KEYWORDS
    if lang in ("de", "nl") and lens_key in local:
        return lang, local[lens_key]
    lang = lang if lang in ("es", "pt") else "en"
    return lang, base[lens_key][lang]


def queries_for(cc: str, lens_key: str, days: int = 30) -> list[tuple[str, str]]:
    """[(via, consulta)] de las capas 'abiertas', 'curadas' y 'global' para el par."""
    qs = [("abierta", f"{q} when:{days}d") for q in lang_terms(cc, lens_key, "queries")[1]]
    sites = SITES.get(cc, {})
    curated = list(dict.fromkeys(sites.get("general", []) + sites.get(lens_key, [])
                                 + COMPLAINT_SITES + (["reclameaqui.com.br"] if cc == "BR" else [])))
    kw = " OR ".join(lang_terms(cc, lens_key, "keywords")[1])
    for i in range(0, len(curated), MAX_SITES_PER_QUERY):
        chunk = curated[i:i + MAX_SITES_PER_QUERY]
        qs.append(("curada", f"({' OR '.join('site:' + d for d in chunk)}) ({kw}) when:{days}d"))
    glob = GLOBAL_SITES.get(lens_key, [])
    if glob:
        gkw = " OR ".join(KEYWORDS[lens_key]["en"])
        qs.append(("global", f"({' OR '.join('site:' + d for d in glob)}) ({gkw}) when:{days}d"))
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
