"""
Email service for authentication-related emails.

Handles:
- Email verification emails
- Password reset emails
- Token generation/validation using itsdangerous

Uses itsdangerous URLSafeTimedSerializer for secure, time-limited tokens.
Tokens are URL-safe and include timestamp for expiration checking.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from app.config import settings
from app.services.exceptions import TokenExpiredError, InvalidCredentialsError


logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending authentication-related emails.

    Token generation uses itsdangerous for secure, time-limited tokens.
    Email sending uses SMTP (configurable via settings).
    """

    def __init__(self) -> None:
        """Initialize the email service with serializer for token generation."""
        self._serializer = URLSafeTimedSerializer(
            settings.jwt_secret_key,
            salt="email-verification-salt"
        )
        self._reset_serializer = URLSafeTimedSerializer(
            settings.jwt_secret_key,
            salt="password-reset-salt"
        )

    def generate_verification_token(self, email: str) -> str:
        """
        Generate a secure email verification token.

        Args:
            email: The email address to encode in the token

        Returns:
            URL-safe token string
        """
        return self._serializer.dumps(email)

    def validate_verification_token(self, token: str) -> str:
        """
        Validate an email verification token.

        Args:
            token: The token to validate

        Returns:
            The email address encoded in the token

        Raises:
            TokenExpiredError: If the token has expired
            InvalidCredentialsError: If the token is invalid
        """
        max_age = settings.email_verification_expire_hours * 3600
        try:
            email = self._serializer.loads(token, max_age=max_age)
            return email
        except SignatureExpired:
            raise TokenExpiredError(
                "Email verification link has expired. Please request a new one.",
                token_type="verification"
            )
        except BadSignature:
            raise InvalidCredentialsError("Invalid verification token")

    def generate_password_reset_token(self, email: str) -> str:
        """
        Generate a secure password reset token.

        Args:
            email: The email address to encode in the token

        Returns:
            URL-safe token string
        """
        return self._reset_serializer.dumps(email)

    def validate_password_reset_token(self, token: str) -> str:
        """
        Validate a password reset token.

        Args:
            token: The token to validate

        Returns:
            The email address encoded in the token

        Raises:
            TokenExpiredError: If the token has expired
            InvalidCredentialsError: If the token is invalid
        """
        max_age = settings.password_reset_expire_hours * 3600
        try:
            email = self._reset_serializer.loads(token, max_age=max_age)
            return email
        except SignatureExpired:
            raise TokenExpiredError(
                "Password reset link has expired. Please request a new one.",
                token_type="reset"
            )
        except BadSignature:
            raise InvalidCredentialsError("Invalid password reset token")

    def send_verification_email(self, email: str, token: str) -> bool:
        """
        Send an email verification email.

        Args:
            email: Recipient email address
            token: Verification token

        Returns:
            True if email was sent successfully, False otherwise
        """
        verification_url = f"{settings.frontend_url}/verify-email?token={token}"

        subject = "Verify your email - Investment Portfolio Analyzer"
        html_body = f"""
        <html>
        <body>
            <h2>Welcome to Investment Portfolio Analyzer!</h2>
            <p>Please verify your email address by clicking the link below:</p>
            <p><a href="{verification_url}">Verify Email</a></p>
            <p>Or copy and paste this URL into your browser:</p>
            <p>{verification_url}</p>
            <p>This link will expire in {settings.email_verification_expire_hours} hours.</p>
            <p>If you didn't create an account, you can safely ignore this email.</p>
        </body>
        </html>
        """
        text_body = f"""
        Welcome to Investment Portfolio Analyzer!

        Please verify your email address by visiting:
        {verification_url}

        This link will expire in {settings.email_verification_expire_hours} hours.

        If you didn't create an account, you can safely ignore this email.
        """

        return self._send_email(email, subject, html_body, text_body)

    def send_password_reset_email(self, email: str, token: str) -> bool:
        """
        Send a password reset email.

        Args:
            email: Recipient email address
            token: Password reset token

        Returns:
            True if email was sent successfully, False otherwise
        """
        reset_url = f"{settings.frontend_url}/reset-password?token={token}"

        subject = "Reset your password - Investment Portfolio Analyzer"
        html_body = f"""
        <html>
        <body>
            <h2>Password Reset Request</h2>
            <p>You requested to reset your password. Click the link below to proceed:</p>
            <p><a href="{reset_url}">Reset Password</a></p>
            <p>Or copy and paste this URL into your browser:</p>
            <p>{reset_url}</p>
            <p>This link will expire in {settings.password_reset_expire_hours} hour(s).</p>
            <p>If you didn't request a password reset, you can safely ignore this email.
               Your password will not be changed.</p>
        </body>
        </html>
        """
        text_body = f"""
        Password Reset Request

        You requested to reset your password. Visit this link to proceed:
        {reset_url}

        This link will expire in {settings.password_reset_expire_hours} hour(s).

        If you didn't request a password reset, you can safely ignore this email.
        Your password will not be changed.
        """

        return self._send_email(email, subject, html_body, text_body)

    def _send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
    ) -> bool:
        """
        Send an email using SMTP.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML version of the email body
            text_body: Plain text version of the email body

        Returns:
            True if email was sent successfully, False otherwise
        """
        if not settings.is_email_configured:
            logger.warning(
                f"Email not configured. Would have sent email to {to_email}: {subject}"
            )
            # In development/test, log the email instead of sending
            if settings.environment in ("development", "test"):
                logger.info(f"Email body: {text_body[:500]}...")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
            msg["To"] = to_email

            # Attach both plain text and HTML versions
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            # Connect and send
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)

            logger.info(f"Email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
