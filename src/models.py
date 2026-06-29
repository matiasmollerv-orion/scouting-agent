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
