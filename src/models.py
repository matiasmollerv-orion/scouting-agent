from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RawItem(BaseModel):
    """Item crudo tal como lo entrega una fuente, antes de normalizar."""

    source: str
    title: str
    url: str
    published_at: Optional[datetime] = None
    text: str = ""
    # Señal cruda de tracción: upvotes, comentarios, puntos, etc.
    engagement: int = 0
    raw_id: str = ""


class Item(BaseModel):
    """Item normalizado al schema común que consume el pipeline."""

    source: str
    title: str
    url: str
    published_at: Optional[datetime] = None
    text: str = ""
    engagement: int = 0

    def dedup_key(self) -> str:
        return self.url.split("?")[0].rstrip("/").lower()


class Signal(str, Enum):
    ALTA = "Alta"
    MEDIA = "Media"
    BAJA = "Baja"


class QualitativeSignal(BaseModel):
    nivel: Signal
    evidencia: str


class ScoredItem(BaseModel):
    """Resultado del análisis de Claude para un candidato."""

    title: str
    url: str
    source: str

    # Score objetivo (lo único numérico, 0-40)
    problema_score: int = Field(ge=0, le=25)
    barrera_score: int = Field(ge=0, le=15)

    # Señales cualitativas (juicio del modelo, no suman al número)
    replicabilidad: QualitativeSignal
    ventana: QualitativeSignal
    tamano_mercado: QualitativeSignal

    resumen: str

    # Campos informativos
    b2b_o_b2c: str
    componente_ia: bool
    tipo_fundador: str
    mercado_actual: str
    company_url: str = ""        # homepage del producto/empresa (distinta del artículo)
    funding_raised: str = ""     # ej: "$3.2M seed", "€1.4M", "bootstrapped", "desconocido"
    stage: str = ""              # ej: "Pre-seed", "Seed", "Series A", "Bootstrapped"

    # Análisis de oportunidad (v2)
    por_que_ahora: str = ""      # timing: qué cambió recientemente que habilita la idea
    modelo_negocio: str = ""     # cómo cobra: ticket, recurrencia, quién paga
    competencia_local: str = ""  # player en Chile/LatAm si existe, o "no identificada"
    fit_tesis: str = ""          # categoría de la tesis del fundador a la que mapea
    next_step: str = ""          # acción concreta de validación en 1 línea
    valida_idea_propia: str = ""  # nombre de la idea ya brainstormeada que este candidato valida, si aplica

    # Contexto de la empresa (v3) — extractivos, solo si el texto los menciona
    fundadores: str = ""         # nombres reales de fundadores, o "no identificados"
    redes_sociales: str = ""     # handle/URL de X, LinkedIn, etc. si aparece en el texto
    fit_yc: str = ""             # "Alto|Medio|Bajo" — ¿se parece a lo que YC financia hoy?

    # Naturaleza del candidato (v4) — no todo lo fetcheado es una empresa
    # replicable: mucho es análisis periodístico de una tendencia con varios
    # players mencionados, no un producto único a estudiar.
    tipo_candidato: str = ""     # "Empresa específica" | "Tendencia" | "Reflexión"

    @property
    def objetivo_total(self) -> int:
        return self.problema_score + self.barrera_score

    def passes_gate(self, min_objetivo: int = 24) -> bool:
        return (
            self.objetivo_total >= min_objetivo
            and self.replicabilidad.nivel != Signal.BAJA
            and Signal.ALTA
            in {
                self.replicabilidad.nivel,
                self.ventana.nivel,
                self.tamano_mercado.nivel,
            }
        )
