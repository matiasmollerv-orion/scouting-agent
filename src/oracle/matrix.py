"""Matriz del Oracle: lentes × países, frecuencias y agenda mensual.

Aprobado por Matías (2026-09-19): 17 países, 11 lentes, frecuencia por lente
(mensual / bimensual / trimestral) y matriz PARCIAL (cada lente solo en los
países donde su señal es fuerte). Los 6 países "core" se visitan a la frecuencia
del lente; los demás ("rot") cada trimestre.

Los lentes salen de las categorías de la tesis en prompts/score.md. Cada uno
define QUIÉN tiene la necesidad y QUÉ señales buscar — la necesidad puede estar
expresada (queja) o latente (brecha / fuerza_externa / oferta), así las búsquedas
son precisas. Editar este archivo cambia la agenda sin tocar el resto.
"""
from __future__ import annotations

from dataclasses import dataclass

# clave -> (nombre, tier). core = frecuencia del lente; rot = cada trimestre.
COUNTRIES: dict[str, tuple[str, str]] = {
    "CL": ("Chile", "core"), "BR": ("Brasil", "core"), "MX": ("México", "core"),
    "US": ("Estados Unidos", "core"), "ES": ("España", "core"), "UK": ("Reino Unido", "core"),
    "PE": ("Perú", "rot"), "CO": ("Colombia", "rot"), "AR": ("Argentina", "rot"),
    "DE": ("Alemania", "rot"), "NL": ("Países Bajos", "rot"),
    "AU": ("Australia y Nueva Zelanda", "rot"), "IN": ("India", "rot"),
    "CN": ("China", "rot"), "IL": ("Israel", "rot"), "KR": ("Corea del Sur", "rot"),
    "SG": ("Singapur", "rot"),
}
# Quejas locales poco accesibles (idioma, bloqueos, mercado chico): ahí se
# prioriza minería de señales de OFERTA (qué se financia, lanza y crece).
SENALES_OFERTA = {"CN", "IL", "KR", "SG"}
ROT_PERIOD = 3  # meses entre visitas de un país "rot"


@dataclass(frozen=True)
class Lens:
    key: str
    name: str
    freq: int  # meses entre visitas (países core)
    definition: str
    countries: tuple[str, ...]


LENSES: tuple[Lens, ...] = (
    Lens("futuro_trabajo", "Futuro del trabajo", 1,
         "Actores: pymes y scale-ups de 5-300 personas, equipos remotos, freelancers (NO solo "
         "grandes corporaciones). Necesidad: hacer más con menos gente — agentes de IA que "
         "absorben tareas administrativas, gestionar y coordinar equipos sin RRHH ni PMO, medir "
         "output. Señales típicas: brecha (procesos manuales, cargos administrativos repetidos en "
         "ofertas de empleo), queja (reseñas 1-3 estrellas de herramientas de gestión de equipos), "
         "oferta (startups nuevas).",
         ("CL", "BR", "MX", "PE", "CO", "AR", "US", "UK", "ES", "DE", "NL", "AU", "IN", "IL", "SG", "KR")),
    Lens("adopcion_ia", "Adopción de IA (empresas y personas)", 1,
         "Actores: empresas de cualquier tamaño y profesionales (incl. ejecutivos no técnicos) que "
         "NO usan IA o la usan mal — la ausencia de uso ES la señal, no hace falta que se quejen. "
         "Necesidad: saber por dónde empezar, capacitación por rol, casos de uso por función, "
         "gobernanza, medir retorno. Señales: brecha (encuestas de adopción por tamaño y país, "
         "ofertas de empleo 'AI lead'), oferta (consultoras y servicios que crecen), fuerza_externa "
         "(regulación de IA).",
         ("CL", "BR", "MX", "PE", "CO", "AR", "US", "UK", "ES", "DE", "NL", "AU", "IN", "CN", "IL", "KR", "SG")),
    Lens("ia_real", "IA aplicada al mundo real", 1,
         "Actores: negocios con operación física o conversación presencial (tiendas, plantas, "
         "faenas, clínicas, flotas, hogares) y sus supervisores. Necesidad: eficiencia o calidad "
         "donde hoy se depende de supervisión humana o intuición — coaching a vendedores por audio, "
         "seguridad laboral, productividad de línea, control de calidad, mermas — usando cámaras, "
         "audio, wearables o sensores. Señales: oferta (startups y pilotos con clientes reales), "
         "brecha (procesos supervisados a mano), fuerza_externa (leyes de grabación y privacidad: "
         "barrera clave). Excluir dev tools y software de oficina puro.",
         ("CL", "BR", "MX", "US", "UK", "ES", "DE", "NL", "IL", "CN", "KR", "SG", "IN")),
    Lens("fintech", "Fintech y seguros (amplio)", 1,
         "Actores: personas (incl. no bancarizadas), independientes, pymes, empresas y quienes las "
         "atienden. Necesidad: hábitos financieros sanos, acceso a crédito e inversión, pagos, "
         "seguros, gasto corporativo, y modelos genuinamente nuevos (crédito comunitario, datos "
         "alternativos de crédito para quien no tiene historial). Señales: queja (reguladores y "
         "ombudsman), brecha (bancarización, penetración de seguros e inversión), oferta (modelos "
         "nuevos), fuerza_externa (open finance, regulación de pagos). Excluir 'otro neobank o app "
         "de trading más' sin modelo distinto.",
         ("CL", "BR", "MX", "PE", "CO", "AR", "US", "UK", "ES", "DE", "AU", "IN", "CN", "IL", "KR", "SG")),
    Lens("salud_bienestar", "Salud, bienestar y longevidad", 1,
         "Actores: consumidores, pacientes, clínicas y profesionales, y empresas con beneficios "
         "para empleados. Necesidad: bienestar personalizado, estética no invasiva y biotecnología "
         "estética, prevención, sueño, salud mental accesible, longevidad. Señales: oferta "
         "(productos y protocolos que crecen), fuerza_externa (regulación sanitaria: barrera), "
         "queja (clínicas, suplementos).",
         ("CL", "BR", "MX", "US", "UK", "ES", "DE", "NL", "AU", "IN", "IL", "KR", "SG")),
    Lens("ops_b2b", "Eficiencia operacional de empresas (B2B)", 2,
         "Actores: empresas de cualquier tamaño y sector, sobre todo pymes y medianas. Necesidad: "
         "eficientar la operación de punta a punta — ventas y cotización, compras, "
         "facturación y cobranza, atención al cliente, reportes, cumplimiento. NO gestión de "
         "personas (otro lente), NO sensores físicos (otro lente), NO logística ni bodegaje (otro "
         "lente), NO lo específico de exportadores (otro lente). Señales: brecha (procesos en planilla, adopción de ERP y CRM por tamaño), "
         "queja (reseñas de ERP/CRM, pagos a 60-90 días), oferta.",
         ("CL", "BR", "MX", "PE", "CO", "AR", "US", "UK", "ES", "DE", "NL", "AU", "IN")),
    Lens("comercio", "Comercio y marketplaces", 2,
         "Actores: vendedores online, comercios sin canal digital, compradores. Necesidad: operar y "
         "vender mejor online, logística y devoluciones, confianza, categorías de consumo en alza, "
         "marketplaces verticales o de nicho. Señales: queja (vendedores sobre comisiones, "
         "suspensiones, logística), oferta (categorías que explotan), brecha (comercio sin "
         "presencia digital). Excluir marketplaces genéricos que compiten directo con MeLi/Rappi.",
         ("CL", "BR", "MX", "PE", "CO", "AR", "US", "UK", "ES", "DE", "AU", "IN", "CN", "KR", "SG")),
    Lens("contenido", "Contenido: creadores y marcas", 2,
         "Actores: creadores que viven de su presencia online, y marcas, empresas y pymes que "
         "producen contenido (marketing, employer branding, ventas). Necesidad: producir contenido "
         "de calidad a escala sin 'AI slop', monetizar, gestionar marcas y sponsors, medir retorno, "
         "finanzas de ingresos irregulares, comunidad. Señales: queja (monetización, costo y tiempo "
         "de producir), oferta (herramientas, agencias), brecha (marcas pyme sin contenido).",
         ("CL", "BR", "MX", "AR", "CO", "US", "UK", "ES", "IN", "CN", "KR", "SG")),
    Lens("exportadoras", "Industrias exportadoras y de recursos", 3,
         "Actores: exportadores, productores y operadores de faena (agro, minería, pesca y "
         "acuicultura), medianos y chicos. Necesidad: cumplir normas de mercados destino, "
         "trazabilidad, menos rechazos y mermas, eficiencia de planta. Señales: fuerza_externa "
         "(normativa de destino, rechazos en frontera), brecha (procesos aún en planilla), queja "
         "(gremios).",
         ("CL", "PE", "CO", "BR", "MX", "AR", "ES", "NL", "AU", "US", "IN")),
    Lens("inmobiliario", "Inmobiliario y construcción", 3,
         "Actores: compradores, arrendatarios, propietarios, corredores, desarrolladoras y "
         "constructoras. Necesidad: cómo se compra, renta, financia y gestiona una propiedad "
         "(fraccionamiento, property management, nuevos esquemas de acceso a vivienda) y cómo se "
         "construye (modular, prefabricado, materiales, tecnología integrada). Señales: queja "
         "(arriendo e inmobiliarias), fuerza_externa (déficit habitacional, regulación), oferta "
         "(formatos y modelos nuevos).",
         ("CL", "BR", "MX", "CO", "US", "UK", "ES", "DE", "NL", "AU", "SG", "KR")),
    Lens("servicios_hogar", "Servicios del hogar y locales", 3,
         "Actores: hogares y prestadores pequeños o informales (limpieza, reparaciones, mudanzas, "
         "cuidado de niños, mayores y mascotas), especialmente vía WhatsApp. Necesidad: encontrar, "
         "contratar y pagar con confianza; precios transparentes; digitalizar lo análogo "
         "('tradicional reinventado'). Señales: queja (incumplimiento, precios opacos), brecha "
         "(informalidad), oferta ('el X de Y').",
         ("CL", "BR", "MX", "PE", "CO", "AR", "ES", "IN", "US")),
    Lens("tradicional", "Negocios tradicionales reinventados", 1,
         "Actores: personas y pymes de industrias probadas — lavandería, tienda de artículos, "
         "ferretería, farmacia, panadería, gimnasio, supermercado, restaurante, ecommerce, "
         "servicios para el hogar, manufactura — mal servidas por el incumbente típico: "
         "fragmentado, informal, caro, lento o con mala experiencia. NO es minería de casos de "
         "éxito (eso va al scouting semanal, que sí los captura y los premia); acá el HUECO es el "
         "sujeto — un segmento, geografía o parte del proceso que el formato de siempre no resuelve "
         "bien, usando como evidencia que en otra parte alguien YA lo resolvió con una vuelta de "
         "tuerca en producto, modelo de negocio, distribución, tecnología/automatización, "
         "experiencia o formato (misma taxonomía que el scouting semanal). Señales: brecha "
         "(fragmentación, informalidad, mala experiencia del formato de siempre), queja (clientes "
         "del incumbente), oferta (una vuelta de tuerca que ya funciona en otro país o industria "
         "análoga, como evidencia de que el hueco se puede cerrar así). Excluir: gigantes que ya "
         "son el status quo (Walmart, Amazon, Zara), franquicias globales conocidas, startups de "
         "software puro, y una empresa exitosa sola sin un hueco local identificable detrás.",
         ("CL", "BR", "MX", "PE", "CO", "AR", "US", "UK", "ES", "DE", "NL", "AU", "IN", "KR", "SG", "CN")),
    Lens("servicios_ia", "Servicios operados por IA (AI-native)", 1,
         "Actores: empresas (sobre todo pymes y medianas) y personas que HOY le pagan a una firma o "
         "proveedor externo por un trabajo de trastienda o servicio profesional — contabilidad y "
         "libros, seguros y cotización, facturación y reclamos médicos, trámites legales y "
         "regulatorios, comercio exterior y aduana, arriendos y títulos, licitaciones y subsidios, "
         "impuestos, cuentas por pagar. Lo que se busca es el HUECO: un servicio que el cliente ya "
         "paga y que sigue caro, lento, opaco o con errores, y cuyo resultado se puede verificar "
         "contra una regla o norma — así lo puede entregar terminado un sistema de agentes con un "
         "equipo humano chico, cobrado por unidad (por trámite, por mes de libros) y no por hora. "
         "EVIDENCIA PRIORITARIA: quejas, reseñas y comentarios de clientes sobre la solución NO-IA "
         "actual (el contador, el corredor, el gestor: tardan, cobran caro, se equivocan), que es la "
         "que se puede reemplazar. Señales: queja (reseñas y reclamos del proveedor humano o del "
         "software que usan), brecha (trabajo tercerizado y verificable que aún se hace a mano), "
         "fuerza_externa (regulación que multiplica el trámite), oferta (un servicio AI-native que "
         "ya funciona en otro país o vertical: cliente, precio por unidad, margen). Prueba de entrada: "
         "(1) ¿ya se terceriza hoy? y (2) ¿tiene una respuesta correcta verificable? Excluir: "
         "herramientas que el cliente opera él mismo, agencias que venden horas, wrappers sin "
         "trabajo terminado. Después de encontrar el segmento, su diseño (unidad, intake, motor, "
         "reglas, revisión, entrega, precio, distribución) se evalúa en el análisis profundo.",
         ("CL", "BR", "MX", "PE", "CO", "AR", "US", "UK", "ES", "DE", "NL", "AU", "IN", "IL", "SG")),
    Lens("logistica", "Logística, bodegaje y fulfillment", 2,
         "Actores: vendedores online, marcas, pymes y operadores logísticos. Necesidad: costo, "
         "velocidad y confiabilidad del almacenaje y la entrega — bodegaje y bodegas compartidas, "
         "fulfillment y 3PL para ecommerce, última milla (incluida fuera de las grandes ciudades), "
         "cold chain, logística inversa (devoluciones), cross-border, automatización de bodegas. "
         "Cuentan tanto operadores y modelos de servicio nuevos (activos propios o livianos) como "
         "las herramientas que los habilitan. Señales: oferta (operadores y modelos que crecen, "
         "financiamiento), queja (vendedores sobre costos de envío, 3PL y devoluciones), brecha "
         "(bodegaje y última milla en ciudades intermedias), fuerza_externa (aduanas y normativa de "
         "comercio electrónico). Excluir: huelgas, tarifas de navieras y grandes aerolíneas sin ángulo "
         "de negocio nuevo.",
         ("CL", "BR", "MX", "PE", "CO", "AR", "US", "UK", "ES", "DE", "NL", "AU", "IN", "CN", "SG", "KR")),
)

LENS_BY_KEY = {l.key: l for l in LENSES}


def _schedule() -> dict[tuple[str, str], tuple[int, int]]:
    """(país, lente) -> (período_en_meses, offset). El offset se reparte en
    ronda entre los países del mismo lente y período, así la carga mensual
    queda pareja en vez de agruparse."""
    out: dict[tuple[str, str], tuple[int, int]] = {}
    for lens in LENSES:
        counters: dict[int, int] = {}
        for cc in lens.countries:
            period = lens.freq if COUNTRIES[cc][1] == "core" else ROT_PERIOD
            i = counters.get(period, 0)
            counters[period] = i + 1
            out[(cc, lens.key)] = (period, i % period)
    return out


SCHEDULE = _schedule()


def month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def due_pairs(mi: int) -> list[tuple[str, str]]:
    """Combinaciones (país, lente) que tocan en el mes `mi`."""
    return [pair for pair, (period, off) in SCHEDULE.items() if period == 1 or mi % period == off]


def pair_label(cc: str, lens_key: str) -> str:
    return f"{COUNTRIES[cc][0]} × {LENS_BY_KEY[lens_key].name}"
