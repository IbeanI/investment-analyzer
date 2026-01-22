# tests/routers/test_upload_api.py
"""
API layer tests for file upload endpoints.

Tests:
- GET /upload/formats - List supported file formats
- POST /upload/transactions - Upload transactions from file

These tests verify the HTTP layer using FastAPI's TestClient with
mocked upload service to avoid actual Yahoo Finance calls.
"""

import io
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_NAME", "Test App")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-chars-long")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models import Base, User, Portfolio
from app.services.auth.jwt_handler import JWTHandler
from app.services.upload.service import UploadResult, UploadError
from app.routers.upload import get_upload_service


# =============================================================================
# TEST DATABASE SETUP
# =============================================================================

@pytest.fixture(scope="function")
def test_engine():
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
def test_db(test_engine) -> Session:
    """Create a database session."""
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
def mock_upload_service():
    """Create a mock upload service."""
    service = MagicMock()
    service.process_file.return_value = UploadResult(
        success=True,
        filename="test.csv",
        total_rows=5,
        created_count=5,
        skipped_count=0,
        error_count=0,
        errors=[],
        warnings=[],
        created_transaction_ids=[1, 2, 3, 4, 5],
    )
    return service


@pytest.fixture(scope="function")
def client(test_db: Session, mock_upload_service) -> TestClient:
    """Create TestClient with database and service overrides."""

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    def override_get_upload_service():
        return mock_upload_service

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_upload_service] = override_get_upload_service

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def seed_user(db: Session, email: str = "test@example.com") -> User:
    """Create a test user."""
    user = User(
        email=email,
        hashed_password="hashed",
        is_email_verified=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_portfolio(db: Session, user: User, name: str = "Test Portfolio") -> Portfolio:
    """Create a test portfolio."""
    portfolio = Portfolio(user_id=user.id, name=name, currency="EUR")
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


def get_auth_headers(user: User) -> dict[str, str]:
    """Get authorization headers with JWT token."""
    jwt_handler = JWTHandler()
    token = jwt_handler.create_access_token(user_id=user.id, email=user.email)
    return {"Authorization": f"Bearer {token}"}


def create_csv_file(content: str = None) -> io.BytesIO:
    """Create a CSV file in memory."""
    if content is None:
        content = """date,action,ticker,reference_exchange,quantity,price,price_currency,fee,fee_currency
2024-01-15,Buy,AAPL,NASDAQ,10,185.50,USD,0,USD
2024-01-16,Buy,MSFT,NASDAQ,5,390.00,USD,0,USD"""
    return io.BytesIO(content.encode("utf-8"))


# =============================================================================
# TEST: GET /upload/formats
# =============================================================================

class TestGetSupportedFormats:
    """Tests for GET /upload/formats endpoint."""

    def test_get_formats_success(self, client: TestClient, test_db: Session):
        """Should return list of supported file formats."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        response = client.get("/upload/formats", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "extensions" in data
        assert "content_types" in data
        assert ".csv" in data["extensions"]
        assert "text/csv" in data["content_types"]


# =============================================================================
# TEST: POST /upload/transactions
# =============================================================================

class TestUploadTransactions:
    """Tests for POST /upload/transactions endpoint."""

    def test_upload_success(self, client: TestClient, test_db: Session, mock_upload_service):
        """Should upload file and return success response."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        csv_file = create_csv_file()

        response = client.post(
            f"/upload/transactions?portfolio_id={portfolio.id}",
            files={"file": ("transactions.csv", csv_file, "text/csv")},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["created_count"] == 5
        assert data["error_count"] == 0
        assert len(data["created_transaction_ids"]) == 5
        mock_upload_service.process_file.assert_called_once()

    def test_upload_with_date_format(self, client: TestClient, test_db: Session, mock_upload_service):
        """Should pass date format to service."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        csv_file = create_csv_file()

        response = client.post(
            f"/upload/transactions?portfolio_id={portfolio.id}&date_format=US",
            files={"file": ("transactions.csv", csv_file, "text/csv")},
            headers=headers,
        )

        assert response.status_code == 200
        # Verify date_format was passed
        call_kwargs = mock_upload_service.process_file.call_args.kwargs
        assert call_kwargs["date_format"].value == "US"

    def test_upload_with_errors(self, client: TestClient, test_db: Session, mock_upload_service):
        """Should return error details when upload has validation errors."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        mock_upload_service.process_file.return_value = UploadResult(
            success=False,
            filename="test.csv",
            total_rows=5,
            created_count=0,
            error_count=2,
            errors=[
                UploadError(
                    row_number=2,
                    stage="validation",
                    error_type="invalid_date",
                    message="Invalid date format",
                    field="date",
                ),
                UploadError(
                    row_number=3,
                    stage="validation",
                    error_type="invalid_quantity",
                    message="Quantity must be positive",
                    field="quantity",
                ),
            ],
            created_transaction_ids=[],
        )

        csv_file = create_csv_file()

        response = client.post(
            f"/upload/transactions?portfolio_id={portfolio.id}",
            files={"file": ("transactions.csv", csv_file, "text/csv")},
            headers=headers,
        )

        assert response.status_code == 200  # 200 because request was valid
        data = response.json()
        assert data["success"] is False
        assert data["error_count"] == 2
        assert len(data["errors"]) == 2
        assert data["errors"][0]["row_number"] == 2
        assert data["errors"][0]["field"] == "date"

    def test_upload_requires_auth(self, client: TestClient, test_db: Session):
        """Should return 401 when not authenticated."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)

        csv_file = create_csv_file()

        response = client.post(
            f"/upload/transactions?portfolio_id={portfolio.id}",
            files={"file": ("transactions.csv", csv_file, "text/csv")},
        )

        assert response.status_code == 401

    def test_upload_portfolio_not_found(self, client: TestClient, test_db: Session):
        """Should return 404 when portfolio doesn't exist."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        csv_file = create_csv_file()

        response = client.post(
            "/upload/transactions?portfolio_id=99999",
            files={"file": ("transactions.csv", csv_file, "text/csv")},
            headers=headers,
        )

        assert response.status_code == 404

    def test_upload_portfolio_forbidden(self, client: TestClient, test_db: Session):
        """Should return 403 when user doesn't own portfolio."""
        user1 = seed_user(test_db, email="user1@example.com")
        user2 = seed_user(test_db, email="user2@example.com")
        portfolio = seed_portfolio(test_db, user1)
        headers = get_auth_headers(user2)

        csv_file = create_csv_file()

        response = client.post(
            f"/upload/transactions?portfolio_id={portfolio.id}",
            files={"file": ("transactions.csv", csv_file, "text/csv")},
            headers=headers,
        )

        assert response.status_code == 403

    def test_upload_missing_portfolio_id(self, client: TestClient, test_db: Session):
        """Should return 422 when portfolio_id is missing."""
        user = seed_user(test_db)
        headers = get_auth_headers(user)

        csv_file = create_csv_file()

        response = client.post(
            "/upload/transactions",
            files={"file": ("transactions.csv", csv_file, "text/csv")},
            headers=headers,
        )

        assert response.status_code == 422

    def test_upload_missing_file(self, client: TestClient, test_db: Session):
        """Should return 422 when file is missing."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        response = client.post(
            f"/upload/transactions?portfolio_id={portfolio.id}",
            headers=headers,
        )

        assert response.status_code == 422

    def test_upload_file_too_large(self, client: TestClient, test_db: Session):
        """Should return 413 when file exceeds size limit."""
        user = seed_user(test_db)
        portfolio = seed_portfolio(test_db, user)
        headers = get_auth_headers(user)

        # Create a file larger than the limit (default 10MB)
        # We'll patch the constant to make testing easier
        with patch("app.routers.upload.MAX_UPLOAD_FILE_SIZE_BYTES", 100):
            large_content = "x" * 200  # 200 bytes > 100 byte limit
            large_file = io.BytesIO(large_content.encode())

            response = client.post(
                f"/upload/transactions?portfolio_id={portfolio.id}",
                files={"file": ("large.csv", large_file, "text/csv")},
                headers=headers,
            )

            assert response.status_code == 413
            assert "too large" in response.json()["message"].lower()
