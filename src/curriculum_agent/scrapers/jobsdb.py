from __future__ import annotations

from curriculum_agent.models import StakeholderEvidence
from curriculum_agent.scrapers.base import BaseScraper


class JobsDBScraper(BaseScraper):
    source_name = "JobsDB"

    async def scrape(self, query: str, max_results: int = 100) -> list[StakeholderEvidence]:
        # TODO: implement with Playwright + BeautifulSoup
        raise NotImplementedError
