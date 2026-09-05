import smtplib
from email.message import EmailMessage


class EmailSendError(Exception):
    """Raised when sending an email via SMTP fails for any reason."""

    pass


class SMTPEmailClient:
    def __init__(self, host: str, port: int, username: str, password: str, from_email: str):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email

    def send(self, to_address: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = to_address
        message["Subject"] = subject
        message.set_content(body)

        try:
            with smtplib.SMTP(self._host, self._port) as smtp:
                smtp.starttls()
                smtp.login(self._username, self._password)
                smtp.send_message(message)
        except Exception as e:
            raise EmailSendError(str(e)) from e
