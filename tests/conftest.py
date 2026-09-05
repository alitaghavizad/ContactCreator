import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("APOLLO_API_KEY", "test-key")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.db import engine
    from app.main import app
    from app.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as test_client:
        yield test_client
