from unittest.mock import MagicMock

import httpx

from app.apollo_client import ApolloClient, SearchCriteria, build_search_params


def test_build_search_params_includes_titles_and_locations():
    criteria = SearchCriteria(titles=["Engineering Manager"], locations=["Yerevan", "EU remote"])

    params = build_search_params(criteria)

    assert params["person_titles"] == ["Engineering Manager"]
    assert params["person_locations"] == ["Yerevan", "EU remote"]
    assert params["per_page"] == 25
    assert "organization_industry_tag_ids" not in params


def test_build_search_params_includes_industries_when_given():
    criteria = SearchCriteria(titles=["Recruiter"], locations=["Armenia"], industries=["banking"])

    params = build_search_params(criteria)

    assert params["organization_industry_tag_ids"] == ["banking"]


def test_search_people_parses_response_into_apollo_person():
    mock_http = MagicMock(spec=httpx.Client)
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "people": [
            {
                "name": "Jane Doe",
                "title": "Engineering Manager",
                "linkedin_url": "https://linkedin.com/in/janedoe",
                "email": "jane@example.com",
                "organization": {"name": "Example Bank", "primary_domain": "example.com"},
            }
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_http.post.return_value = mock_response

    client = ApolloClient(api_key="test-key", http_client=mock_http)
    criteria = SearchCriteria(titles=["Engineering Manager"], locations=["Yerevan"])

    results = client.search_people(criteria)

    assert len(results) == 1
    person = results[0]
    assert person.name == "Jane Doe"
    assert person.company_name == "Example Bank"
    assert person.company_domain == "example.com"
    assert person.linkedin_url == "https://linkedin.com/in/janedoe"
    assert person.email == "jane@example.com"

    mock_http.post.assert_called_once()
    _, kwargs = mock_http.post.call_args
    assert kwargs["headers"]["x-api-key"] == "test-key"
