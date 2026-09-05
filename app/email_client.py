import smtplib
import ssl
from email.message import EmailMessage

# Guard against a hung SMTP connection permanently consuming a threadpool worker:
# every route in this app is a synchronous `def`, so a blocking socket read would
# otherwise tie up a bounded AnyIO worker thread forever.
SMTP_TIMEOUT_SECONDS = 30


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
        try:
            # Built inside the try: a CR/LF in any header value raises ValueError,
            # which must surface as an EmailSendError like any other send failure.
            message = EmailMessage()
            message["From"] = self._from_email
            message["To"] = to_address
            message["Subject"] = subject
            message.set_content(body)

            with smtplib.SMTP(self._host, self._port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
                # An explicit default context verifies the server certificate and
                # hostname; smtplib's own default (ssl._create_stdlib_context) does
                # neither, which would expose the app password to an on-path server.
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self._username, self._password)
                smtp.send_message(message)
        except Exception as e:
            raise EmailSendError(str(e)) from e
