"""
Password hashing and verification using bcrypt.

Uses passlib with bcrypt backend for secure password hashing.
Cost factor is set to 12 (default) which provides good security
while keeping hash time reasonable (~250ms).

Security considerations:
- Bcrypt automatically handles salt generation
- Timing-safe comparison prevents timing attacks
- Cost factor can be increased as hardware improves
"""

from passlib.context import CryptContext


# Configure bcrypt with cost factor 12
# "deprecated='auto'" allows seamless algorithm upgrades
_pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


class PasswordService:
    """
    Service for password hashing and verification.

    Uses bcrypt algorithm with cost factor 12.
    All methods are stateless and can be called as class methods.
    """

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a plaintext password using bcrypt.

        Args:
            password: The plaintext password to hash

        Returns:
            The bcrypt hash string (includes algorithm, cost, salt, and hash)

        Example:
            >>> hashed = PasswordService.hash_password("mypassword123")
            >>> hashed.startswith("$2b$")
            True
        """
        return _pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Verify a plaintext password against a bcrypt hash.

        Uses timing-safe comparison to prevent timing attacks.

        Args:
            plain_password: The plaintext password to verify
            hashed_password: The bcrypt hash to compare against

        Returns:
            True if password matches, False otherwise

        Example:
            >>> hashed = PasswordService.hash_password("mypassword123")
            >>> PasswordService.verify_password("mypassword123", hashed)
            True
            >>> PasswordService.verify_password("wrongpassword", hashed)
            False
        """
        return _pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def needs_rehash(hashed_password: str) -> bool:
        """
        Check if a hash needs to be upgraded (e.g., cost factor increased).

        This is useful when upgrading security parameters over time.
        Call this after successful authentication to keep hashes current.

        Args:
            hashed_password: The existing bcrypt hash

        Returns:
            True if the hash should be regenerated with current settings

        Example:
            # After successful login:
            if PasswordService.needs_rehash(user.hashed_password):
                user.hashed_password = PasswordService.hash_password(plain_password)
                db.commit()
        """
        return _pwd_context.needs_update(hashed_password)
