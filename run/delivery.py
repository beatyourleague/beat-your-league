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
- **Nothing is sent to someone who asked us to stop.** That check lives HERE
  (``run.suppress``), because it binds every sender at once.
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
# Every email carries a Reply-To. The emails promise "reply stop" and "reply
# to any report", and the From address (reports@) is not an inbox anybody
# reads — only hello@ forwards (LAUNCH.md). So a reply must land there even
# when EMAIL_REPLY_TO was never set; it is read at send time, not import time.
CONTACT_INBOX = "hello@beatyourleague.com"


def reply_to_address() -> str:
    return os.environ.get("EMAIL_REPLY_TO", "").strip() or CONTACT_INBOX


DEFAULT_REPLY_TO = None


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
    # A League Pass SEAT has no subscription to cancel, so its target is a
    # mailto stop request instead (render/report.unsubscribe_target), which
    # the stop list then honours (run/suppress.py).
    unsubscribe: str | None = None


@dataclass
class SendResult:
    message: Message
    ok: bool
    detail: str
    skipped: bool = False
    # Skipped because the address asked us to stop (run/suppress.py). Always
    # also ``skipped``, so every existing count treats it as not-a-failure;
    # this flag lets a runner say so separately.
    suppressed: bool = False


SUPPRESSED = "suppressed — this address asked us to stop"


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


def sent_entries(path: Path | None = None) -> list[dict]:
    """Every readable line of the send log, with its ``sent_at`` — for the
    questions a key alone cannot answer ("how many free reports went out
    today?"). A damaged line is skipped, as in :func:`load_sent`."""
    path = path or SENT_LOG
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("key"):
            entries.append(entry)
    return entries


def record_sent(key: str, provider: str, message_id: str,
                path: Path | None = None) -> None:
    path = path or SENT_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"key": key, "provider": provider, "message_id": message_id,
             "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


DRY_PROVIDER = "dry"


# --------------------------------------------------------------------- #
# after the send: did it bounce? (pre-launch review, critique #1)
# --------------------------------------------------------------------- #
#
# The join page hands the buyer's typed address straight to Stripe, locked, so
# a typo ("gmial.com") is a buyer who paid and whose welcome and every report
# go to a dead mailbox — each logged as sent, and nothing ever reading the
# bounce. The likely end is a "not received" chargeback. The send log already
# holds every Resend message id, so after a run the intake asks Resend what
# happened to the recent ones. Only Resend has a per-message lookup wired here;
# other providers are skipped and say so.

RESEND_EMAILS_API = "https://api.resend.com/emails"
# Resend's `last_event` values that mean the mail did not land, or landed and
# was reported as spam.
UNDELIVERED_EVENTS = ("bounced", "complained", "failed")
# Mail to addresses nobody has paid for (a stranger can type them into a
# public form): a bounce there is counted, never an alarm about a buyer.
UNPAID_KEY_PREFIXES = ("trial-", "seat-unmatched-", "seat-full-", "seat-confirm-",
                       "launch-", "run-")
# A buyer's first contact — where a mistyped address shows up first.
FIRST_CONTACT_PREFIXES = ("welcome-", "preseason-")
# The key the lookup uses. Resend's "Sending access" key (the one that mails,
# RESEND_API_KEY) "can only send emails": reading one back needs a Full access
# key, so the lookup has a secret of its own and falls back to the sending key
# only to find out, in one request, that it cannot (pre-launch review).
BOUNCE_KEY_ENV = "RESEND_READ_KEY"
BOUNCE_LOOKBACK_HOURS = 48
BOUNCE_MAX_LOOKUPS = 30
# Resend's default rate limit is 2 requests a second.
BOUNCE_PAUSE_SECONDS = 0.55


class KeyCannotRead(DeliveryError):
    """The Resend key was refused for a read (HTTP 401/403): it is a sending
    key. Every further lookup would be refused the same way."""


def resend_last_event(message_id: str, api_key: str) -> str | None:
    """Resend's ``last_event`` for one message id, or None when it has none.
    Raises DeliveryError (never echoing the key) when the lookup fails, and
    KeyCannotRead when the key itself is refused."""
    from urllib.parse import quote
    request = urllib.request.Request(
        f"{RESEND_EMAILS_API}/{quote(message_id, safe='')}", method="GET",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json",
                 "User-Agent": "beat-your-league-intake"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise KeyCannotRead(f"HTTP {exc.code} from Resend") from None
        raise DeliveryError(f"HTTP {exc.code} from Resend") from None
    except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
        raise DeliveryError(f"could not reach Resend: "
                            f"{exc.reason if hasattr(exc, 'reason') else exc}") from None
    except json.JSONDecodeError:
        raise DeliveryError("Resend returned something that is not JSON") from None
    event = data.get("last_event") if isinstance(data, dict) else None
    return str(event) if isinstance(event, str) and event else None


def lookup_order(entries, now: datetime,
                 lookback_hours: int = BOUNCE_LOOKBACK_HOURS) -> list[dict]:
    """The send-log entries worth asking Resend about, most important first:
    Resend sends with a real message id from the last ``lookback_hours`` —
    first contact with a buyer (welcome, roster report) first, then other
    paid mail, then mail to unpaid addresses, newest first within each. Pure."""
    from datetime import timedelta
    since = now - timedelta(hours=lookback_hours)
    picked: list[tuple[int, datetime, dict]] = []
    for entry in entries:
        key = str(entry.get("key") or "")
        message_id = str(entry.get("message_id") or "")
        if entry.get("provider") != "resend" or not key or not message_id \
                or ":" in message_id:          # "resend:accepted" carries no id
            continue
        try:
            at = datetime.fromisoformat(str(entry.get("sent_at") or ""))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at < since or at > now:
            continue
        rank = (0 if key.startswith(FIRST_CONTACT_PREFIXES)
                else 2 if key.startswith(UNPAID_KEY_PREFIXES) else 1)
        picked.append((rank, at, entry))
    picked.sort(key=lambda item: (item[0], -item[1].timestamp()))
    return [entry for _rank, _at, entry in picked]


@dataclass
class BounceReport:
    """What a bounce check found. ``paid`` are (send-log key, event) pairs for
    mail somebody paid for — each an alarm; ``unpaid`` the same for mail to
    addresses nobody has paid for. Keys carry no address (the send log's own
    rule), so this is safe to print."""

    paid: list[tuple[str, str]]
    unpaid: list[tuple[str, str]]
    checked: int = 0
    errors: int = 0
    skipped: str = ""
    # The key was refused for a read: nothing was checked, and nothing will be
    # until the owner gives the lookup a key that can read (RESEND_READ_KEY).
    key_cannot_read: bool = False


def check_bounces(entries, now: datetime, api_key: str | None = None, *,
                  lookup=None, limit: int = BOUNCE_MAX_LOOKUPS,
                  pause: float = BOUNCE_PAUSE_SECONDS) -> BounceReport:
    """Ask Resend what became of the recent sends (``lookup_order``), at most
    ``limit`` lookups. Never raises; never prints or returns an address."""
    import time
    report = BounceReport(paid=[], unpaid=[])
    if api_key is None:
        api_key = (os.environ.get(BOUNCE_KEY_ENV, "").strip()
                   or os.environ.get("RESEND_API_KEY", "").strip())
    if lookup is None:
        if not api_key:
            report.skipped = f"neither {BOUNCE_KEY_ENV} nor RESEND_API_KEY is set"
            return report
        lookup = lambda message_id: resend_last_event(message_id, api_key)  # noqa: E731
    for index, entry in enumerate(lookup_order(entries, now)[:limit]):
        if index and pause:
            time.sleep(pause)
        try:
            event = lookup(str(entry["message_id"]))
        except KeyCannotRead:
            # One refusal answers for the rest: stop rather than spend the
            # run's sleeps on 29 more of them.
            report.errors += 1
            report.key_cannot_read = True
            break
        except DeliveryError:
            report.errors += 1
            continue
        report.checked += 1
        if event in UNDELIVERED_EVENTS:
            key = str(entry["key"])
            (report.unpaid if key.startswith(UNPAID_KEY_PREFIXES)
             else report.paid).append((key, event))
    return report


def send_all(messages: list[Message], provider: Provider | None = None,
             sender: str = DEFAULT_FROM, reply_to: str | None = DEFAULT_REPLY_TO,
             sent_log: Path | None = None,
             resend_anyway: bool = False,
             suppress_file: Path | None = None) -> list[SendResult]:
    """Send each message once, and never to an address that asked us to stop.
    Never raises: failures come back as results."""
    from run.digest import DigestError, secret as log_secret
    from run.suppress import (SuppressionError, is_suppressed, load_suppressed,
                              owed_anyway)
    provider = provider or build_provider()
    reply_to = reply_to or reply_to_address()
    sent_log = sent_log or SENT_LOG
    # The stop list (run/suppress.py) is checked HERE, once, for every runner:
    # "you're off within 10 business days" is promised to League Pass seats
    # and the waitlist, and a check living in each runner is one runner short
    # the first time somebody adds a sender. Unreadable fails CLOSED — a late
    # Tuesday is recoverable; mailing somebody who asked us to stop is not.
    #
    # Checking an address against the list needs its keyed code, and so does
    # every address-derived send-log key: without LOG_SECRET a real send
    # REFUSES (run/digest.py). A dry run with an empty list checks nothing,
    # so a local preview still works before the secret exists.
    try:
        stopped = load_suppressed(suppress_file)
        if stopped or provider.name != DRY_PROVIDER:
            log_secret()
    except (SuppressionError, DigestError) as exc:
        return [SendResult(m, ok=False, detail=f"not sent: {exc}") for m in messages]
    already = set() if resend_anyway else load_sent(sent_log)
    results: list[SendResult] = []
    for message in messages:
        # Before the resend override and the send log: --resend re-mails a
        # week, it never re-mails somebody who said stop.
        if stopped and is_suppressed(message.to, stopped) and not owed_anyway(message.key):
            results.append(SendResult(message, ok=True, detail=SUPPRESSED,
                                      skipped=True, suppressed=True))
            continue
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
