import smtplib
import ssl
from unittest.mock import MagicMock, patch

import pytest

from app.email_client import EmailSendError, SMTPEmailClient


@patch("app.email_client.smtplib.SMTP")
def test_send_calls_starttls_login_and_send_message(mock_smtp_cls):
    mock_smtp = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

    client = SMTPEmailClient(
        host="smtp.gmail.com",
        port=587,
        username="me@gmail.com",
        password="app-password",
        from_email="me@gmail.com",
    )
    client.send("jane@example.com", "Hello", "Hi Jane, ...")

    # A timeout is required: without one a hung connection blocks a worker thread forever.
    mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=30)

    # STARTTLS must verify the server certificate and hostname. smtplib's own default
    # (starttls() with no context) uses ssl._create_stdlib_context(), which has
    # verify_mode=CERT_NONE / check_hostname=False and would leak the app password.
    mock_smtp.starttls.assert_called_once()
    starttls_call = mock_smtp.starttls.call_args
    context = starttls_call.kwargs.get("context")
    if context is None and starttls_call.args:
        # smtplib.starttls(keyfile, certfile, context) - context is the third positional.
        context = starttls_call.args[-1]
    assert context is not None, "starttls() was called without an SSL context"
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True

    mock_smtp.login.assert_called_once_with("me@gmail.com", "app-password")
    mock_smtp.send_message.assert_called_once()

    sent_message = mock_smtp.send_message.call_args[0][0]
    assert sent_message["From"] == "me@gmail.com"
    assert sent_message["To"] == "jane@example.com"
    assert sent_message["Subject"] == "Hello"
    assert sent_message.get_content().strip() == "Hi Jane, ..."


@patch("app.email_client.smtplib.SMTP")
def test_send_raises_email_send_error_on_login_failure(mock_smtp_cls):
    mock_smtp = MagicMock()
    mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

    client = SMTPEmailClient(
        host="smtp.gmail.com",
        port=587,
        username="me@gmail.com",
        password="wrong-password",
        from_email="me@gmail.com",
    )

    with pytest.raises(EmailSendError):
        client.send("jane@example.com", "Hello", "Hi Jane, ...")


@patch("app.email_client.smtplib.SMTP")
def test_send_raises_email_send_error_on_invalid_header_value(mock_smtp_cls):
    """A CR/LF-injection attempt in the recipient must surface as EmailSendError,
    not as a raw ValueError escaping the route's failure handling."""
    mock_smtp = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp

    client = SMTPEmailClient(
        host="smtp.gmail.com",
        port=587,
        username="me@gmail.com",
        password="app-password",
        from_email="me@gmail.com",
    )

    with pytest.raises(EmailSendError):
        client.send("jane@example.com\nBcc: evil@example.com", "Hello", "Hi Jane, ...")

    mock_smtp.send_message.assert_not_called()


@patch("app.email_client.smtplib.SMTP")
def test_send_raises_email_send_error_on_connection_failure(mock_smtp_cls):
    mock_smtp_cls.side_effect = ConnectionRefusedError("connection refused")

    client = SMTPEmailClient(
        host="smtp.gmail.com",
        port=587,
        username="me@gmail.com",
        password="app-password",
        from_email="me@gmail.com",
    )

    with pytest.raises(EmailSendError):
        client.send("jane@example.com", "Hello", "Hi Jane, ...")
