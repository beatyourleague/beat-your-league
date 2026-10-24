"""Provider error text, made safe for a public log (SEC-11 / INFRA-15).

The Actions logs of a public repo are readable by anyone, and a failed send
printed up to 300 characters of the provider's own error body. Those bodies
carry addresses: Postmark's 406 lists the inactive recipients, Resend's
testing-mode refusal names the account's own login, an SMTP refusal quotes
the recipient, and ``repr()`` of an unexpected exception can hold a whole
message. So every failure detail is passed through ``redact`` before it can
be printed: addresses become ``<address>`` and anything shaped like one of our
providers' keys becomes ``<key>``. What went wrong (the status, the reason)
survives; who it was about does not.
"""

from __future__ import annotations

import re

# Deliberately loose: a false positive costs a word in a log line, a false
# negative publishes somebody's address.
_ADDRESS = re.compile(r"[^\s@<>()\[\]{}\"',;:]+@[^\s@<>()\[\]{}\"',;:]+\.[A-Za-z]{2,}")
# Stripe (sk_/rk_/pk_/whsec_), Resend (re_), and any bearer credential.
_KEY = re.compile(r"\b(?:sk|rk|pk|re|whsec)_(?:live_|test_)?[A-Za-z0-9_]{8,}")
_BEARER = re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/=-]{8,}")


def redact(text: object) -> str:
    """``text`` with every address and credential-shaped string replaced."""
    out = _ADDRESS.sub("<address>", str(text))
    out = _KEY.sub("<key>", out)
    return _BEARER.sub(lambda m: f"{m.group(1)} <key>", out)
