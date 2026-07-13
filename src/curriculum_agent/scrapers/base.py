from __future__ import annotations

from abc import ABC, abstractmethod

from curriculum_agent.models import StakeholderEvidence


class BaseScraper(ABC):
    source_name: str

    @abstractmethod
    async def scrape(self, query: str, max_results: int = 100) -> list[StakeholderEvidence]: ...
