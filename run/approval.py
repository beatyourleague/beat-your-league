"""The owner's approval for a dispatch that mails every subscriber (INFRA-06).

Usage — on the owner's own machine, with LOG_SECRET in the shell:
    make notice-approval PAGE=terms EFFECTIVE=2026-11-15     # then paste the summary
    python -m run.approval notice terms 2026-11-15 -          # the same: summary on stdin
    python -m run.approval notice terms 2026-11-15 'What changes, as you will paste it'
prints a code (and, on stderr, the words it signed); paste it into the
change-notice workflow's `approval` box beside the same page, date and summary.
A summary on the command line goes in SINGLE quotes: in double quotes the shell
turns "$69" into "9" and the code is signed over other words. Read from stdin
(``-``), nothing touches it. The workflow checks it before sending:
    python -m run.approval verify notice <code> terms 2026-11-15 "..."

Why. ``GH_DISPATCH_TOKEN`` — the fine-grained token the form Worker uses to
start the crons on time — carries Actions: Read and write, and that is enough
to dispatch ANY workflow, including change-notice.yml, whose `summary` is
mailed as written to everyone entitled. A stolen token was therefore a way to
send every subscriber attacker-written text from our own domain. The code is
an HMAC under LOG_SECRET (a GitHub secret the token cannot read) over the
exact page, date and summary, so a dispatch that does not carry the owner's
code for those words sends nothing. GitHub environments with required
reviewers would do the same job, but a private repo on the Free plan loses
them, and this works on any plan.

Whitespace in the summary is normalised before signing, so a paste that gains
a trailing space or a line break still matches; any other change does not.
"""

from __future__ import annotations

import argparse
import hmac
import sys

from run.digest import DigestError, keyed

LENGTH = 20          # 80 bits: a guess is hopeless against a dispatch API
KINDS = ("notice",)


def code(kind: str, *fields: str) -> str:
    """The approval code for ``kind`` over ``fields`` (LOG_SECRET required)."""
    if kind not in KINDS:
        raise ValueError(f"unknown approval kind {kind!r}")
    # NUL never occurs in an address, so this can never equal the input of a
    # send-log or stop-list code made with the same secret.
    message = "\x00".join(["byl-approval-v1", kind, *(" ".join(f.split()) for f in fields)])
    return keyed(message, LENGTH)


def verify(kind: str, given: str, *fields: str) -> bool:
    return hmac.compare_digest(code(kind, *fields), (given or "").strip().lower())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("words", nargs="+",
                        help="notice PAGE EFFECTIVE SUMMARY, or verify notice CODE PAGE EFFECTIVE SUMMARY")
    args = parser.parse_args(argv)
    words = args.words
    try:
        if words[0] == "verify":
            if len(words) != 6:
                parser.error("verify notice CODE PAGE EFFECTIVE SUMMARY")
            if verify(words[1], words[2], *words[3:]):
                print("Approval matches: the owner signed this page, date and summary.")
                return 0
            print("REFUSED: the approval code does not match this page, date and summary "
                  "(make one locally: python -m run.approval notice PAGE EFFECTIVE SUMMARY). "
                  "Nothing was sent.", file=sys.stderr)
            return 1
        if len(words) != 4:
            parser.error("notice PAGE EFFECTIVE SUMMARY")
        if words[3] == "-":
            if sys.stdin.isatty():
                print("Paste the summary exactly as it goes in the workflow's box, "
                      "then press Enter:", file=sys.stderr)
            words[3] = sys.stdin.readline().rstrip("\r\n")
        if not words[3].strip():
            parser.error("the summary is empty")
        signed = code(words[0], *words[1:])
        # The owner's own terminal: the words, so a mangled paste shows here
        # rather than as a refusal in the workflow.
        print(f"Signed: {words[0]} · {words[1]} · {words[2]} · {' '.join(words[3].split())}",
              file=sys.stderr)
        print(signed)
        return 0
    except (DigestError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
