from dataclasses import dataclass, field
from typing import Optional

import httpx

APOLLO_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/search"


@dataclass
class SearchCriteria:
    titles: list[str]
    locations: list[str]
    industries: list[str] = field(default_factory=list)
    per_page: int = 25


@dataclass
class ApolloPerson:
    name: str
    title: Optional[str]
    company_name: Optional[str]
    company_domain: Optional[str]
    linkedin_url: Optional[str]
    email: Optional[str]


def build_search_params(criteria: SearchCriteria) -> dict:
    """Translate intake criteria into Apollo's mixed_people/search request body.

    Field names follow Apollo's documented People Search API as of this
    writing; verify against https://apolloio.github.io/apollo-api-docs/
    if Apollo has changed their schema since.
    """
    params: dict = {
        "person_titles": criteria.titles,
        "person_locations": criteria.locations,
        "per_page": criteria.per_page,
        "page": 1,
    }
    if criteria.industries:
        params["organization_industry_tag_ids"] = criteria.industries
    return params


class ApolloClient:
    def __init__(self, api_key: str, http_client: Optional[httpx.Client] = None):
        self._api_key = api_key
        self._http = http_client or httpx.Client(timeout=30.0)

    def search_people(self, criteria: SearchCriteria) -> list[ApolloPerson]:
        params = build_search_params(criteria)
        response = self._http.post(
            APOLLO_SEARCH_URL,
            json=params,
            headers={"x-api-key": self._api_key, "Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        return [_to_apollo_person(p) for p in data.get("people", [])]


def _to_apollo_person(raw: dict) -> ApolloPerson:
    organization = raw.get("organization") or {}
    return ApolloPerson(
        name=raw.get("name", ""),
        title=raw.get("title"),
        company_name=organization.get("name"),
        company_domain=organization.get("primary_domain"),
        linkedin_url=raw.get("linkedin_url"),
        email=raw.get("email"),
    )
