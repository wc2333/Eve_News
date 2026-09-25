"""SMTP delivery: HTML body plus a plain-text alternative, with retries."""

from __future__ import annotations

import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path

from .config import EmailConfig

log = logging.getLogger("evenews.mailer")


class MailError(Exception):
    pass


def build_message(
    config: EmailConfig,
    *,
    subject: str,
    html: str,
    text: str,
    attachments: list[Path] | None = None,
    to: list[str] | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    recipients = [address.strip() for address in (to or config.to) if address.strip()]
    if not recipients:
        raise MailError("没有收件人")
    message["To"] = ", ".join(recipients)
    if config.cc:
        message["Cc"] = ", ".join(config.cc)
        recipients = recipients + [c.strip() for c in config.cc if c.strip()]
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message["X-Mailer"] = "EveNews"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    for path in attachments or []:
        path = Path(path)
        if path.is_file():
            message.add_attachment(
                path.read_bytes(),
                maintype="text",
                subtype="html" if path.suffix == ".html" else "plain",
                filename=path.name,
            )
    message.recipients = recipients  # type: ignore[attr-defined]
    return message


def _smtp_client(config: EmailConfig) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if config.security == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=config.timeout, context=context)
    else:
        client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.timeout)
        if config.security == "starttls":
            client.starttls(context=context)
    return client


def send(config: EmailConfig, message: EmailMessage) -> None:
    recipients = getattr(message, "recipients", None) or []
    last_error: Exception | None = None
    for attempt in range(max(1, config.retries + 1)):
        try:
            with _smtp_client(config) as client:
                client.ehlo()
                if config.username and config.password:
                    client.login(config.username, config.password)
                client.send_message(message, from_addr=parseaddr(config.from_address)[1], to_addrs=recipients)
            log.info("已发送给 %d 位收件人", len(recipients))
            return
        except Exception as exc:  # noqa: BLE001 - surface every SMTP failure the same way
            last_error = exc
            log.warning("发送失败（第 %d 次）：%s", attempt + 1, exc)
            if attempt < config.retries:
                time.sleep(3 * (attempt + 1))
    raise MailError(f"SMTP 发送失败: {last_error}") from last_error


def send_digest(
    config: EmailConfig,
    *,
    subject: str,
    html: str,
    text: str,
    attachments: list[Path] | None = None,
    to: list[str] | None = None,
) -> list[str]:
    message = build_message(config, subject=subject, html=html, text=text, attachments=attachments, to=to)
    send(config, message)
    return list(getattr(message, "recipients", []))
