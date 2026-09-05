import smtplib
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

    mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587)
    mock_smtp.starttls.assert_called_once()
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
