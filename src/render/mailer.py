from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from .. import config


def send_html(subject: str, html: str, sender_name: str = "Scouting Semanal") -> bool:
    """Envía un email HTML vía Gmail SMTP. Retorna True si salió OK."""
    if not config.GMAIL_USER or not config.GMAIL_APP_PASSWORD:
        print("[email] GMAIL_USER / GMAIL_APP_PASSWORD no configuradas — se omite el envío")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, config.GMAIL_USER))
    msg["To"] = config.EMAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
            server.sendmail(config.GMAIL_USER, [config.EMAIL_TO], msg.as_string())
        print(f"[email] enviado a {config.EMAIL_TO}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"[email] error de autenticación Gmail: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"[email] error SMTP: {e}")
    return False
