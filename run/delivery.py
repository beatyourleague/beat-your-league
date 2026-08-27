"""Sending the reports — the last manual step in the weekly pipeline.

Provider-agnostic on purpose. The Substack-vs-Stripe decision changes who takes
the money and who tells us who is paying; it does not change what a send looks
like. So delivery is one small interface with several backends, chosen by
environment variable, and the pipeline never learns which one it is talking to:

    EMAIL_PROVIDER=dry        write .eml files to disk, send nothing (default)
    EMAIL_PROVIDER=resend     Resend HTTP API      (RESEND_API_KEY)
    EMAIL_PROVIDER=postmark   Postmark HTTP API    (POSTMARK_TOKEN)
    EMAIL_PROVIDER=ses        Amazon SES v2        (AWS_* standard credentials)

Design rules, each learned from a way this goes wrong:

- **Dry run is the default.** A misconfigured cron must never mail 50 people by
  accident; sending is opt-in via an explicit provider name.
- **Never send twice.** Each (subscriber, season, week) send is recorded, and a
  re-run skips what already went out. Reruns are routine — a failed step, a
  resumed workflow — and a subscriber receiving Tuesday's report three times
  reads as broken software.
- **One failure never stops the batch.** Providers rate-limit and time out; the
  other subscribers still get their reports, and the failure is reported.
- **No secrets in logs.** Only provider names and message ids are printed.
- **Nothing is sent to someone who isn't paying.** That check lives in
  ``run.batch``; delivery just refuses to guess by requiring an explicit list.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent
SENT_LOG = REPO_ROOT / "data" / "processed" / "sent.jsonl"
DRY_OUTBOX = REPO_ROOT / "reports" / "outbox"

DEFAULT_FROM = os.environ.get("EMAIL_FROM", "Beat Your League <reports@example.invalid>")
DEFAULT_REPLY_TO = os.environ.get("EMAIL_REPLY_TO") or None


class DeliveryError(RuntimeError):
    """A send failed. Carries no credentials, only what went wrong."""


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    html: str
    text: str
    key: str          # idempotency key: subscriber + season + week
    # Where "stop sending me this" points. For a PAID subscription there is no
    # free list to leave — unsubscribing and cancelling are the same act — so
    # this is the billing portal where the money actually stops, falling back
    # to the terms page's cancel section. Emitted as List-Unsubscribe on every
    # provider: a weekly report went out with no unsubscribe mechanism of any
    # kind and no cancel link in either half, while its own footer said the
    # steps were "on our legal page" (found Aug 24 2026, by reading a
    # delivered draft's headers). No List-Unsubscribe-Post: one-click POST
    # (RFC 8058) promises an endpoint that consumes the request, and a Stripe
    # portal link is not one. Claiming it would be worse than omitting it.
    unsubscribe: str | None = None


@dataclass
class SendResult:
    message: Message
    ok: bool
    detail: str
    skipped: bool = False


# --------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------- #

class Provider(Protocol):
    name: str

    def send(self, message: Message, sender: str, reply_to: str | None) -> str:
        """Deliver one message, returning a provider id. Raise DeliveryError."""


class DryRunProvider:
    """Writes what WOULD be sent. The default, so nothing mails by accident."""

    name = "dry"

    def __init__(self, outbox: Path | None = None) -> None:
        # Resolved here, not in the signature: a module constant baked into a
        # default argument cannot be redirected by a caller or a test.
        self.outbox = outbox or DRY_OUTBOX

    def send(self, message: Message, sender: str, reply_to: str | None) -> str:
        self.outbox.mkdir(parents=True, exist_ok=True)
        mail = EmailMessage()
        mail["From"] = sender
        mail["To"] = message.to
        mail["Subject"] = message.subject
        if reply_to:
            mail["Reply-To"] = reply_to
        if message.unsubscribe:
            mail["List-Unsubscribe"] = f"<{message.unsubscribe}>"
        mail.set_content(message.text)
        mail.add_alternative(message.html, subtype="html")
        path = self.outbox / f"{message.key}.eml"
        path.write_bytes(bytes(mail))
        return f"dry:{path.name}"


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        # Deliberately does not echo the request: it carries the API key.
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise DeliveryError(f"HTTP {exc.code} from provider: {detail}") from None
    except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
        raise DeliveryError(f"could not reach provider: {exc.reason if hasattr(exc, 'reason') else exc}") from None
    except json.JSONDecodeError:
        return {}


class ResendProvider:
    name = "resend"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def send(self, message: Message, sender: str, reply_to: str | None) -> str:
        payload = {"from": sender, "to": [message.to], "subject": message.subject,
                   "html": message.html, "text": message.text}
        if reply_to:
            payload["reply_to"] = reply_to
        if message.unsubscribe:
            payload["headers"] = {"List-Unsubscribe": f"<{message.unsubscribe}>"}
        data = _post_json("https://api.resend.com/emails", payload,
                          {"Authorization": f"Bearer {self.api_key}"})
        return str(data.get("id") or "resend:accepted")


class PostmarkProvider:
    name = "postmark"

    def __init__(self, token: str) -> None:
        self.token = token

    def send(self, message: Message, sender: str, reply_to: str | None) -> str:
        payload = {"From": sender, "To": message.to, "Subject": message.subject,
                   "HtmlBody": message.html, "TextBody": message.text,
                   "MessageStream": os.environ.get("POSTMARK_STREAM", "outbound")}
        if reply_to:
            payload["ReplyTo"] = reply_to
        if message.unsubscribe:
            payload["Headers"] = [{"Name": "List-Unsubscribe",
                                   "Value": f"<{message.unsubscribe}>"}]
        data = _post_json("https://api.postmarkapp.com/email", payload,
                          {"X-Postmark-Server-Token": self.token,
                           "Accept": "application/json"})
        return str(data.get("MessageID") or "postmark:accepted")


class SESProvider:
    name = "ses"

    def __init__(self) -> None:
        try:
            import boto3  # noqa: F401  (optional dependency)
        except ImportError:
            raise DeliveryError(
                "EMAIL_PROVIDER=ses needs boto3 installed (pip install boto3)") from None

    def send(self, message: Message, sender: str, reply_to: str | None) -> str:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
        client = boto3.client("sesv2")
        simple = {
            "Subject": {"Data": message.subject},
            "Body": {"Html": {"Data": message.html}, "Text": {"Data": message.text}},
        }
        if message.unsubscribe:
            # SESv2 Simple content gained Headers in 2023; older boto3 rejects
            # the key, and a send that fails is worse than a missing header on
            # a fallback provider, so it degrades rather than raising.
            simple["Headers"] = [{"Name": "List-Unsubscribe",
                                  "Value": f"<{message.unsubscribe}>"}]
        body = {"Simple": simple}
        try:
            response = client.send_email(
                FromEmailAddress=sender,
                Destination={"ToAddresses": [message.to]},
                Content=body,
                **({"ReplyToAddresses": [reply_to]} if reply_to else {}),
            )
        except (BotoCoreError, ClientError) as exc:
            if message.unsubscribe and "Headers" in simple:
                simple.pop("Headers")
                try:
                    response = client.send_email(
                        FromEmailAddress=sender,
                        Destination={"ToAddresses": [message.to]},
                        Content={"Simple": simple},
                        **({"ReplyToAddresses": [reply_to]} if reply_to else {}))
                    return str(response.get("MessageId") or "ses:accepted")
                except (BotoCoreError, ClientError):
                    pass
            raise DeliveryError(f"SES rejected the send: {exc}") from None
        return str(response.get("MessageId") or "ses:accepted")


class SMTPProvider:
    """Generic SMTP, for anyone who would rather not use an HTTP API."""

    name = "smtp"

    def __init__(self) -> None:
        self.host = os.environ.get("SMTP_HOST", "")
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.user = os.environ.get("SMTP_USER", "")
        self.password = os.environ.get("SMTP_PASSWORD", "")
        if not (self.host and self.user and self.password):
            raise DeliveryError(
                "EMAIL_PROVIDER=smtp needs SMTP_HOST, SMTP_USER and SMTP_PASSWORD")

    def send(self, message: Message, sender: str, reply_to: str | None) -> str:
        mail = EmailMessage()
        mail["From"] = sender
        mail["To"] = message.to
        mail["Subject"] = message.subject
        if reply_to:
            mail["Reply-To"] = reply_to
        if message.unsubscribe:
            mail["List-Unsubscribe"] = f"<{message.unsubscribe}>"
        mail.set_content(message.text)
        mail.add_alternative(message.html, subtype="html")
        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(self.user, self.password)
                server.send_message(mail)
        except (smtplib.SMTPException, OSError) as exc:
            raise DeliveryError(f"SMTP send failed: {exc}") from None
        return "smtp:accepted"


def build_provider(name: str | None = None) -> Provider:
    """Resolve the provider from the environment. Defaults to dry-run."""
    choice = (name or os.environ.get("EMAIL_PROVIDER") or "dry").strip().lower()
    if choice in ("dry", "", "none"):
        return DryRunProvider()
    if choice == "resend":
        key = os.environ.get("RESEND_API_KEY", "")
        if not key:
            raise DeliveryError("EMAIL_PROVIDER=resend needs RESEND_API_KEY")
        return ResendProvider(key)
    if choice == "postmark":
        token = os.environ.get("POSTMARK_TOKEN", "")
        if not token:
            raise DeliveryError("EMAIL_PROVIDER=postmark needs POSTMARK_TOKEN")
        return PostmarkProvider(token)
    if choice == "ses":
        return SESProvider()
    if choice == "smtp":
        return SMTPProvider()
    raise DeliveryError(f"unknown EMAIL_PROVIDER {choice!r} — expected one of "
                        "dry, resend, postmark, ses, smtp")


# --------------------------------------------------------------------- #
# idempotency — a subscriber must never get Tuesday's report twice
# --------------------------------------------------------------------- #

def load_sent(path: Path | None = None) -> set[str]:
    path = path or SENT_LOG
    if not path.is_file():
        return set()
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            keys.add(json.loads(line)["key"])
        except (json.JSONDecodeError, KeyError):
            continue  # a damaged line must not license a duplicate send
    return keys


def record_sent(key: str, provider: str, message_id: str,
                path: Path | None = None) -> None:
    path = path or SENT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"key": key, "provider": provider, "message_id": message_id,
             "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


DRY_PROVIDER = "dry"


def send_all(messages: list[Message], provider: Provider | None = None,
             sender: str = DEFAULT_FROM, reply_to: str | None = DEFAULT_REPLY_TO,
             sent_log: Path | None = None,
             resend_anyway: bool = False) -> list[SendResult]:
    """Send each message once. Never raises: failures come back as results."""
    provider = provider or build_provider()
    sent_log = sent_log or SENT_LOG
    already = set() if resend_anyway else load_sent(sent_log)
    results: list[SendResult] = []
    for message in messages:
        if message.key in already:
            results.append(SendResult(message, ok=True, detail="already sent", skipped=True))
            continue
        try:
            message_id = provider.send(message, sender, reply_to)
        except DeliveryError as exc:
            results.append(SendResult(message, ok=False, detail=str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 — one bad send must not end the run
            results.append(SendResult(message, ok=False, detail=f"unexpected: {exc!r}"))
            continue
        # A dry run delivered NOTHING, so it must not claim a delivery. This
        # was recording every draft, which meant `make dry-send` — documented
        # as a safe preview — silently marked every subscriber as already sent,
        # and the real send afterwards skipped them all: a green run with empty
        # inboxes. It also applied to the cron itself, which runs dry until
        # EMAIL_PROVIDER is set, so the first REAL send would have skipped
        # everyone the dry runs had "sent".
        if provider.name != DRY_PROVIDER:
            record_sent(message.key, provider.name, message_id, sent_log)
        results.append(SendResult(message, ok=True, detail=message_id))
    return results
