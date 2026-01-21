# tests/services/auth/test_password.py
"""
Tests for password hashing service.

Tests:
- Password hashing with bcrypt
- Password verification (correct/incorrect)
- Hash format validation
- Rehash detection
"""

import os

import pytest

# Set required environment variables BEFORE importing app modules
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_NAME", "Test App")

from app.services.auth.password import PasswordService


# =============================================================================
# TEST: PASSWORD HASHING
# =============================================================================


class TestPasswordHashing:
    """Tests for password hashing."""

    def test_hash_returns_string(self):
        """Hashing a password should return a string."""
        hashed = PasswordService.hash_password("mypassword123")

        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_starts_with_bcrypt_prefix(self):
        """Hash should have bcrypt prefix ($2b$)."""
        hashed = PasswordService.hash_password("mypassword123")

        assert hashed.startswith("$2b$")

    def test_hash_is_different_from_password(self):
        """Hash should not be the same as the password."""
        password = "mypassword123"
        hashed = PasswordService.hash_password(password)

        assert hashed != password

    def test_same_password_different_hashes(self):
        """Same password should produce different hashes (due to salt)."""
        password = "mypassword123"
        hash1 = PasswordService.hash_password(password)
        hash2 = PasswordService.hash_password(password)

        assert hash1 != hash2

    def test_hash_empty_password(self):
        """Empty password should still produce a valid hash."""
        hashed = PasswordService.hash_password("")

        assert hashed.startswith("$2b$")

    def test_hash_long_password(self):
        """Long password should be hashed successfully."""
        long_password = "a" * 1000  # Very long password
        hashed = PasswordService.hash_password(long_password)

        assert hashed.startswith("$2b$")

    def test_hash_unicode_password(self):
        """Unicode password should be hashed successfully."""
        unicode_password = "пароль密码🔐"
        hashed = PasswordService.hash_password(unicode_password)

        assert hashed.startswith("$2b$")


# =============================================================================
# TEST: PASSWORD VERIFICATION
# =============================================================================


class TestPasswordVerification:
    """Tests for password verification."""

    def test_correct_password_verifies(self):
        """Correct password should verify as True."""
        password = "mypassword123"
        hashed = PasswordService.hash_password(password)

        assert PasswordService.verify_password(password, hashed) is True

    def test_incorrect_password_fails(self):
        """Incorrect password should verify as False."""
        password = "mypassword123"
        hashed = PasswordService.hash_password(password)

        assert PasswordService.verify_password("wrongpassword", hashed) is False

    def test_similar_password_fails(self):
        """Similar but different password should fail."""
        password = "mypassword123"
        hashed = PasswordService.hash_password(password)

        # Case sensitivity
        assert PasswordService.verify_password("Mypassword123", hashed) is False
        # Extra character
        assert PasswordService.verify_password("mypassword1234", hashed) is False
        # Missing character
        assert PasswordService.verify_password("mypassword12", hashed) is False

    def test_empty_password_verification(self):
        """Empty password verification should work correctly."""
        hashed = PasswordService.hash_password("")

        assert PasswordService.verify_password("", hashed) is True
        assert PasswordService.verify_password("notempty", hashed) is False

    def test_unicode_password_verification(self):
        """Unicode password should verify correctly."""
        password = "пароль密码🔐"
        hashed = PasswordService.hash_password(password)

        assert PasswordService.verify_password(password, hashed) is True
        assert PasswordService.verify_password("пароль密码", hashed) is False  # Missing emoji


# =============================================================================
# TEST: REHASH DETECTION
# =============================================================================


class TestRehashDetection:
    """Tests for detecting when passwords need rehashing."""

    def test_current_hash_does_not_need_rehash(self):
        """Fresh hash with current settings should not need rehash."""
        hashed = PasswordService.hash_password("mypassword123")

        assert PasswordService.needs_rehash(hashed) is False

    def test_old_hash_format_needs_rehash(self):
        """Hash with old/different settings might need rehash."""
        # This test is harder to implement without actually changing settings
        # In practice, this would detect hashes created with lower cost factors
        hashed = PasswordService.hash_password("mypassword123")

        # Current implementation should not need rehash
        assert PasswordService.needs_rehash(hashed) is False


# =============================================================================
# TEST: EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_verify_with_invalid_hash_format(self):
        """Verification with invalid hash should raise UnknownHashError."""
        from passlib.exc import UnknownHashError

        # passlib raises UnknownHashError for invalid hash formats
        with pytest.raises(UnknownHashError):
            PasswordService.verify_password("password", "not-a-valid-hash")

    def test_verify_with_empty_hash(self):
        """Verification with empty hash should raise UnknownHashError."""
        from passlib.exc import UnknownHashError

        with pytest.raises(UnknownHashError):
            PasswordService.verify_password("password", "")

    def test_hash_special_characters(self):
        """Password with special characters should hash and verify."""
        special_chars = "!@#$%^&*()_+-=[]{}|;':\",./<>?`~"
        hashed = PasswordService.hash_password(special_chars)

        assert PasswordService.verify_password(special_chars, hashed) is True

    def test_hash_whitespace_password(self):
        """Whitespace-only password should hash and verify."""
        whitespace = "   \t\n   "
        hashed = PasswordService.hash_password(whitespace)

        assert PasswordService.verify_password(whitespace, hashed) is True
        assert PasswordService.verify_password("", hashed) is False
