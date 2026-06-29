from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import RawItem


class Source(ABC):
    """Interfaz común a toda fuente. Agregar Tier 2 = escribir una subclase."""

    name: str

    @abstractmethod
    def fetch(self) -> list[RawItem]:
        """Devuelve items crudos. No debe lanzar: ante error, lista vacía + log."""
        ...
