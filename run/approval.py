"""The owner's approval for a dispatch that mails every subscriber (INFRA-06),
or that shows, exports or erases one person's data (final review SEC-2).

Usage — on the owner's own machine, with LOG_SECRET in the shell:
    make notice-approval PAGE=terms EFFECTIVE=2026-11-15     # then paste the summary
    python -m run.approval notice terms 2026-11-15 -          # the same: summary on stdin
    python -m run.approval notice terms 2026-11-15 'What changes, as you will paste it'
    python -m run.approval privacy delete 0123456789ab        # ACTION CODE
prints a code (and, on stderr, the words it signed); paste it into the
workflow's `approval` box beside the same inputs. A summary on the command
line goes in SINGLE quotes: in double quotes the shell turns "$69" into "9"
and the code is signed over other words. Read from stdin (``-``), nothing
touches it. The workflows check it before acting:
    python -m run.approval verify notice <code> terms 2026-11-15 "..."
    python -m run.approval verify privacy <code> delete 0123456789ab

Why. ``GH_DISPATCH_TOKEN`` — the fine-grained token the form Worker uses to
start the crons on time — carries Actions: Read and write, and that is enough
to dispatch ANY workflow. change-notice.yml mails its `summary` as written to
everyone entitled, so a stolen token was a way to send every subscriber
attacker-written text from our own domain. privacy.yml's (privacy-request) `delete`
takes a 12-hex code that is exactly the suffix of the launch and free-report
keys the public send log carries for every waitlist and free-report mailbox,
so the same token could erase a paying subscriber who had joined the waitlist
— registry row, plans and backups — and `show` printed whether a code holds
registry rows into a public job log (SEC-2). The code is an HMAC under
LOG_SECRET (a GitHub secret the token cannot read) over the exact inputs, so a
dispatch that does not carry the owner's code for them does nothing. GitHub
environments with required reviewers would do the same job, but a private
repo on the Free plan loses them, and this works on any plan.

Whitespace in the inputs is normalised before signing, so a paste that gains
a trailing space or a line break still matches; any other change does not. A
privacy request's action and code are lowercased too (run/privacy.py reads
the code that way), so the approval can never disagree with what is acted on.
"""

from __future__ import annotations

import argparse
import hmac
import sys

from run.digest import DigestError, keyed

LENGTH = 20          # 80 bits: a guess is hopeless against a dispatch API
# Each kind and the inputs its code is signed over, in order.
FIELDS = {"notice": ("PAGE", "EFFECTIVE", "SUMMARY"),
          "privacy": ("ACTION", "CODE")}
KINDS = tuple(FIELDS)
PRIVACY_ACTIONS = ("show", "export", "delete")


def _normalise(kind: str, fields: tuple[str, ...]) -> list[str]:
    words = [" ".join(str(f).split()) for f in fields]
    return [w.lower() for w in words] if kind == "privacy" else words


def code(kind: str, *fields: str) -> str:
    """The approval code for ``kind`` over ``fields`` (LOG_SECRET required)."""
    if kind not in KINDS:
        raise ValueError(f"unknown approval kind {kind!r}")
    if len(fields) != len(FIELDS[kind]):
        raise ValueError(f"{kind} is signed over {' '.join(FIELDS[kind])}")
    if kind == "privacy" and _normalise(kind, fields)[0] not in PRIVACY_ACTIONS:
        raise ValueError(f"a privacy action is one of {', '.join(PRIVACY_ACTIONS)}")
    # NUL never occurs in an address, so this can never equal the input of a
    # send-log or stop-list code made with the same secret.
    message = "\x00".join(["byl-approval-v1", kind, *_normalise(kind, fields)])
    return keyed(message, LENGTH)


def verify(kind: str, given: str, *fields: str) -> bool:
    return hmac.compare_digest(code(kind, *fields), (given or "").strip().lower())


def _usage(kind: str, verifying: bool = False) -> str:
    names = " ".join(FIELDS.get(kind, ("...",)))
    return f"verify {kind} CODE {names}" if verifying else f"{kind} {names}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("words", nargs="+",
                        help="notice PAGE EFFECTIVE SUMMARY | privacy ACTION CODE, "
                             "or verify KIND APPROVAL ...the same inputs")
    args = parser.parse_args(argv)
    words = args.words
    try:
        if words[0] == "verify":
            kind = words[1] if len(words) > 1 else ""
            if kind not in FIELDS or len(words) != 3 + len(FIELDS[kind]):
                parser.error(" or ".join(_usage(k, True) for k in KINDS))
            if verify(kind, words[2], *words[3:]):
                print(f"Approval matches: the owner signed this {kind} "
                      f"({', '.join(FIELDS[kind]).lower()}).")
                return 0
            print(f"REFUSED: the approval code does not match this {kind} request "
                  f"(make one locally: python -m run.approval {_usage(kind)}). "
                  f"Nothing was done.", file=sys.stderr)
            return 1
        kind = words[0]
        if kind not in FIELDS or len(words) != 1 + len(FIELDS[kind]):
            parser.error(" or ".join(_usage(k) for k in KINDS))
        if kind == "notice" and words[3] == "-":
            if sys.stdin.isatty():
                print("Paste the summary exactly as it goes in the workflow's box, "
                      "then press Enter:", file=sys.stderr)
            words[3] = sys.stdin.readline().rstrip("\r\n")
        if kind == "notice" and not words[3].strip():
            parser.error("the summary is empty")
        signed = code(kind, *words[1:])
        # The owner's own terminal: the words, so a mangled paste shows here
        # rather than as a refusal in the workflow.
        print(f"Signed: {kind} · {' · '.join(_normalise(kind, tuple(words[1:])))}",
              file=sys.stderr)
        print(signed)
        return 0
    except (DigestError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
