from dataclasses import dataclass
from typing import Optional

import httpx

HUNTER_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"


@dataclass
class HunterPerson:
    name: str
    title: Optional[str]
    company_name: Optional[str]
    company_domain: Optional[str]
    linkedin_url: Optional[str]
    email: Optional[str]


class HunterClient:
    def __init__(self, api_key: str, http_client: Optional[httpx.Client] = None):
        self._api_key = api_key
        self._http = http_client or httpx.Client(timeout=30.0)

    def domain_search(self, domain: str, limit: int = 25) -> list[HunterPerson]:
        response = self._http.get(
            HUNTER_DOMAIN_SEARCH_URL,
            params={
                "domain": domain,
                "api_key": self._api_key,
                "limit": limit,
                "type": "personal",
            },
        )
        response.raise_for_status()
        data = response.json()
        result = data.get("data") or {}
        company_name = result.get("organization")
        emails = result.get("emails") or []
        return [_to_hunter_person(e, domain, company_name) for e in emails]


def _to_hunter_person(raw: dict, domain: str, company_name: Optional[str]) -> HunterPerson:
    first_name = raw.get("first_name") or ""
    last_name = raw.get("last_name") or ""
    name = f"{first_name} {last_name}".strip() or raw.get("value", "")
    return HunterPerson(
        name=name,
        title=raw.get("position"),
        company_name=company_name,
        company_domain=domain,
        linkedin_url=raw.get("linkedin"),
        email=raw.get("value"),
    )
