from unittest.mock import MagicMock

import httpx
import pytest

from app.hunter_client import HunterAPIError, HunterClient, HunterPerson


def _mock_response(json_data: dict, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://api.hunter.io/v2/domain-search")
    return httpx.Response(status_code, json=json_data, request=request)


def test_domain_search_returns_people():
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response(
        {
            "data": {
                "organization": "Example Bank",
                "emails": [
                    {
                        "first_name": "Jane",
                        "last_name": "Doe",
                        "position": "Engineering Manager",
                        "linkedin": "https://linkedin.com/in/janedoe",
                        "value": "jane@example.com",
                    }
                ],
            }
        }
    )
    client = HunterClient(api_key="test-key", http_client=mock_http)

    people = client.domain_search("example.com", limit=10)

    assert people == [
        HunterPerson(
            name="Jane Doe",
            title="Engineering Manager",
            company_name="Example Bank",
            company_domain="example.com",
            linkedin_url="https://linkedin.com/in/janedoe",
            email="jane@example.com",
        )
    ]
    mock_http.get.assert_called_once_with(
        "https://api.hunter.io/v2/domain-search",
        params={"domain": "example.com", "api_key": "test-key", "limit": 10, "type": "personal"},
    )


def test_domain_search_missing_name_falls_back_to_email_value():
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response(
        {"data": {"organization": None, "emails": [{"value": "person@example.com"}]}}
    )
    client = HunterClient(api_key="test-key", http_client=mock_http)

    people = client.domain_search("example.com")

    assert people[0].name == "person@example.com"
    assert people[0].linkedin_url is None
    assert people[0].title is None


def test_domain_search_raises_hunter_api_error_on_http_status_error():
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response(
        {"errors": [{"details": "invalid api key"}]}, status_code=401
    )
    client = HunterClient(api_key="bad-key", http_client=mock_http)

    with pytest.raises(HunterAPIError):
        client.domain_search("example.com")


def test_domain_search_raises_hunter_api_error_on_request_error():
    mock_http = MagicMock()
    mock_http.get.side_effect = httpx.ConnectError("connection refused")
    client = HunterClient(api_key="test-key", http_client=mock_http)

    with pytest.raises(HunterAPIError):
        client.domain_search("example.com")
