# tests/test_correlation_id.py
"""
Tests for correlation ID middleware and context management.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_NAME", "Test App")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models import Base
from app.utils.context import get_correlation_id, set_correlation_id, clear_correlation_id


class TestCorrelationIdContext:
    """Tests for correlation ID context functions."""

    def test_get_returns_none_when_not_set(self):
        """Should return None when correlation ID is not set."""
        clear_correlation_id()
        assert get_correlation_id() is None

    def test_set_and_get_correlation_id(self):
        """Should set and retrieve correlation ID."""
        set_correlation_id("test-correlation-123")
        assert get_correlation_id() == "test-correlation-123"
        clear_correlation_id()

    def test_clear_correlation_id(self):
        """Should clear correlation ID."""
        set_correlation_id("test-correlation-456")
        clear_correlation_id()
        assert get_correlation_id() is None


class TestCorrelationIdMiddleware:
    """Tests for correlation ID middleware."""

    @pytest.fixture(scope="function")
    def test_engine(self):
        """Create an in-memory SQLite database engine."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        yield engine
        Base.metadata.drop_all(engine)

    @pytest.fixture(scope="function")
    def test_db(self, test_engine) -> Session:
        """Create a database session for tests."""
        TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=test_engine
        )
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    @pytest.fixture
    def client(self, test_db: Session):
        """Create test client with database override."""
        def override_get_db():
            try:
                yield test_db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as c:
            yield c

        app.dependency_overrides.clear()

    def test_generates_correlation_id_when_not_provided(self, client):
        """Should generate correlation ID when not provided in request."""
        response = client.get("/health")

        assert response.status_code == 200
        assert "X-Correlation-ID" in response.headers
        # Should be a valid UUID format
        correlation_id = response.headers["X-Correlation-ID"]
        assert len(correlation_id) == 36  # UUID length
        assert correlation_id.count("-") == 4  # UUID format

    def test_uses_provided_correlation_id(self, client):
        """Should use correlation ID from request header."""
        custom_id = "my-custom-trace-id-123"
        response = client.get(
            "/health",
            headers={"X-Correlation-ID": custom_id}
        )

        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == custom_id

    def test_uses_request_id_header_as_fallback(self, client):
        """Should use X-Request-ID header if X-Correlation-ID not provided."""
        custom_id = "my-request-id-456"
        response = client.get(
            "/health",
            headers={"X-Request-ID": custom_id}
        )

        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == custom_id

    def test_prefers_correlation_id_over_request_id(self, client):
        """Should prefer X-Correlation-ID over X-Request-ID."""
        correlation_id = "correlation-123"
        request_id = "request-456"
        response = client.get(
            "/health",
            headers={
                "X-Correlation-ID": correlation_id,
                "X-Request-ID": request_id,
            }
        )

        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == correlation_id

    def test_correlation_id_consistent_across_request(self, client):
        """Should maintain same correlation ID throughout request."""
        response = client.get("/")

        assert response.status_code == 200
        correlation_id = response.headers.get("X-Correlation-ID")
        assert correlation_id is not None

    def test_different_requests_get_different_ids(self, client):
        """Different requests should get different correlation IDs."""
        response1 = client.get("/health")
        response2 = client.get("/health")

        id1 = response1.headers["X-Correlation-ID"]
        id2 = response2.headers["X-Correlation-ID"]

        assert id1 != id2
