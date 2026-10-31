import os, smtplib
from email.message import EmailMessage


def send_email(to: str, subject: str, body: str):
    """Sends via SMTP if SMTP_HOST is set, otherwise prints + appends to outbox.log (demo mode)."""
    host = os.getenv("SMTP_HOST")
    if host:
        m = EmailMessage()
        m["From"] = os.getenv("SMTP_FROM", "billing@brightloop.test")
        m["To"], m["Subject"] = to, subject
        m.set_content(body)
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
            s.starttls()
            if os.getenv("SMTP_USER"):
                s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS", ""))
            s.send_message(m)
    else:
        text = f"\n--- EMAIL to {to} ---\nSubject: {subject}\n{body}\n"
        print(text)
        with open("outbox.log", "a") as f:
            f.write(text)
