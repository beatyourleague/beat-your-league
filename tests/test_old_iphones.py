"""Every script the site ships must parse and run on an older iPhone.

Found in the promotion review (Nov 2026): one regex in site/join/roster.js
used a lookbehind. Safari only learned lookbehind in 16.4, and a regex LITERAL
is parsed with the file, so on iOS 15 and early iOS 16 the whole of roster.js
threw a SyntaxError before a line of it ran. That includes Chrome on those
phones and the in-app browsers of X, Reddit and Discord, which all use the
same engine. join/ and the bye planner then said "The player list didn't
load", and reloading never fixed it: nobody on those phones could check a
roster or buy.

The floor here is Safari 14. Each script is split into code, strings,
comments and regex literals by a small lexer, so a word in a comment never
trips a check and a use in code is always read as code. The lexer is checked
against node: every regex literal it finds must compile as a RegExp, and each
script, with its strings blanked and its comments dropped, must still parse
as a classic script (which also rules out top-level await).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent / "site"

# Tokens after which a "/" starts a regex rather than a division.
_EXPRESSION_START = set("(,=:[!&|?{};+-*%<>~^")
_EXPRESSION_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new",
                        "delete", "void", "throw", "instanceof", "yield", "await"}


def lex(src: str) -> list[tuple[str, str]]:
    """Split JavaScript into (kind, text): code, string, template, comment, regex."""
    out: list[tuple[str, str]] = []
    i, n, start = 0, len(src), 0
    last = ""                      # the last significant code token
    braces: list[bool] = []        # True for a template literal's ${ ... }

    def flush(end: int) -> None:
        if end > start:
            out.append(("code", src[start:end]))

    while i < n:
        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i) or src.startswith("/*", i):
            flush(i)
            if src[i + 1] == "/":
                j = src.find("\n", i)
                j = n if j < 0 else j
            else:
                j = src.find("*/", i + 2)
                j = n if j < 0 else j + 2
            out.append(("comment", src[i:j]))
            i = start = j
            continue
        if c in "'\"":
            flush(i)
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(("string", src[i:j + 1]))
            i = start = j + 1
            last = "string"
            continue
        if c == "`" or (c == "}" and braces and braces[-1]):
            if c == "}":
                braces.pop()
            flush(i)
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                elif src[j] == "`":
                    j += 1
                    break
                elif src.startswith("${", j):
                    j += 2
                    braces.append(True)
                    break
                else:
                    j += 1
            out.append(("template", src[i:j]))
            i = start = j
            last = "string" if src[j - 1] == "`" else "("
            continue
        if c == "{":
            braces.append(False)
        elif c == "}" and braces:
            braces.pop()
        if c == "/" and (not last or last == "}" or last in _EXPRESSION_START
                         or last in _EXPRESSION_KEYWORDS):
            flush(i)
            j, in_class = i + 1, False
            while j < n and (src[j] != "/" or in_class):
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "\n":
                    raise AssertionError(f"the lexer lost a regex at {src[i:i + 40]!r}")
                j += 1
            j += 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            out.append(("regex", src[i:j]))
            i = start = j
            last = "regex"
            continue
        word = re.match(r"[A-Za-z_$#][\w$]*|\d[\w.]*", src[i:i + 200])
        if word:
            last = word.group(0)
            i += len(last)
            continue
        last = c
        i += 1
    flush(n)
    return out


def site_scripts() -> list[tuple[str, str]]:
    """(label, source) for every script the site ships: each .js file and every
    inline <script> on every page (structured data is JSON, not script)."""
    found = [(str(p.relative_to(SITE)), p.read_text(encoding="utf-8"))
             for p in sorted(SITE.rglob("*.js"))]
    for page in sorted(SITE.rglob("*.html")):
        text = page.read_text(encoding="utf-8")
        tags = re.finditer(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", text, re.S)
        for k, tag in enumerate(tags):
            if "ld+json" not in tag.group(1):
                found.append((f"{page.relative_to(SITE)} inline script {k + 1}", tag.group(2)))
    return found


SCRIPTS = site_scripts()
LEXED = {label: lex(src) for label, src in SCRIPTS}


def _code(tokens: list[tuple[str, str]], templates: bool = False) -> str:
    """The script as code alone: strings blanked and comments gone. Template
    text is dropped too, unless node must parse the result."""
    def piece(kind: str, text: str) -> str:
        if kind == "string" or (kind == "template" and not templates):
            return '""'
        return " " if kind == "comment" else text
    return " ".join(piece(kind, text) for kind, text in tokens)


# (pattern, what it is, the Safari that added it). Each is a SyntaxError or a
# TypeError on the phones this file is about, and none is used today.
LOOKBEHIND = re.compile(r"\(\?<[=!]")
REGEX_RULES = [
    (LOOKBEHIND, "a regex lookbehind", "16.4"),
    (re.compile(r"/[a-z]*d[a-z]*$"), "the regex d flag", "15"),
    (re.compile(r"/[a-z]*v[a-z]*$"), "the regex v flag", "17"),
    (re.compile(r"\(\?[imsx-]+:"), "an inline regex modifier", "none yet"),
]
CODE_RULES = [
    (re.compile(r"\.at\("), ".at()", "15.4"),
    (re.compile(r"\bfindLast(Index)?\b"), "findLast", "15.4"),
    (re.compile(r"\bstructuredClone\b"), "structuredClone", "15.4"),
    (re.compile(r"\bhasOwn\b"), "Object.hasOwn", "15.4"),
    (re.compile(r"\brandomUUID\b"), "crypto.randomUUID", "15.4"),
    (re.compile(r"\bshowModal\b"), "dialog.showModal", "15.4"),
    (re.compile(r"\bgroupBy\b|\bgroupToMap\b|\.group\("), "groupBy / Array.prototype.group",
     "17.4, or never"),
    (re.compile(r"\bto(Sorted|Reversed|Spliced)\b"), "toSorted and its kin", "16"),
    (re.compile(r"\bstatic\s*\{"), "a class static block", "16.4"),
    (re.compile(r"#[A-Za-z_$]"), "a private class field or method", "14.1 / 15"),
    (re.compile(r"\brequestIdleCallback\b"), "requestIdleCallback", "never"),
    (re.compile(r"\bwithResolvers\b"), "Promise.withResolvers", "17.4"),
    (re.compile(r"\badoptedStyleSheets\b|\bnew CSSStyleSheet\b"), "constructable stylesheets",
     "16.4"),
]
# Newer than Safari 15 and in use, so every call must test for it first, in
# the same expression, with a fallback after the "?".
GUARDED = [("AbortSignal.timeout(", "AbortSignal.timeout ?", "16"),
           (".requestSubmit(", "requestSubmit ?", "16")]


def test_the_lexer_reads_every_script_the_site_ships() -> None:
    """A check that reads nothing passes while checking nothing, so the scan
    must cover every .js file and the pages' inline scripts, and must find
    the regex literals that are really there."""
    labels = [label for label, _ in SCRIPTS]
    assert {p.name for p in SITE.rglob("*.js")} >= {"roster.js", "byes.js", "count.js",
                                                     "footer.js", "email-check.js"}
    assert sum(" inline script " in label for label in labels) >= 15, labels
    assert any(label.startswith("join/index.html inline") for label in labels)
    assert any(label.startswith("byes/index.html inline") for label in labels)
    roster = [text for kind, text in LEXED["join/roster.js"] if kind == "regex"]
    assert len(roster) >= 30, roster
    assert r"/([^\s.])(?: K(?= |$))+/gi" in roster
    # And the checks below fire on what they are for, and not on a comment.
    sample = lex('const a = s.replace(/(?<=x) K/g, ""); // look at(this) and (?<=\n'
                 'const b = list.at(-1);')
    assert [t for k, t in sample if k == "regex"] == ["/(?<=x) K/g"]
    assert ".at(" in _code(sample) and "look at" not in _code(sample)


def test_no_site_script_uses_a_regex_lookbehind() -> None:
    """Not in a regex literal, and not in a string handed to new RegExp,
    which throws the same SyntaxError when it runs. Comments may say what
    they like. engine/roster.py keeps its lookbehind: Python has one."""
    for label, tokens in LEXED.items():
        for kind, text in tokens:
            assert kind == "comment" or not LOOKBEHIND.search(text), (
                f"{label}: a lookbehind, which Safari before 16.4 cannot parse, "
                f"so the whole script fails on older iPhones: {text[:120]!r}")


def test_no_site_script_uses_syntax_or_built_ins_safari_14_lacks() -> None:
    """Each of these arrived in Safari 15 or later. A regex flag or class
    syntax is a SyntaxError that stops the whole script; a missing built-in is
    a TypeError that stops it from that line on."""
    for label, tokens in LEXED.items():
        code = _code(tokens)
        for rule, what, version in CODE_RULES:
            hit = rule.search(code)
            assert not hit, (f"{label} uses {what} (Safari {version}): "
                             f"{code[max(0, hit.start() - 50):hit.end() + 20]!r}")
        for kind, text in tokens:
            if kind != "regex":
                continue
            for rule, what, version in REGEX_RULES:
                assert not rule.search(text), f"{label} uses {what} (Safari {version}): {text}"


def test_every_newer_built_in_the_site_uses_is_tested_for_first() -> None:
    """AbortSignal.timeout and form.requestSubmit arrived in Safari 16. Both are
    used, always as `X ? X(...) : fallback`. The older check for AbortSignal
    in test_site.py reads only the pages, so rookie-form.js was never seen."""
    calls = 0
    for label, tokens in LEXED.items():
        code = _code(tokens)
        for call, guard, version in GUARDED:
            for hit in re.finditer(re.escape(call), code):
                calls += 1
                before = code[max(0, hit.start() - 80):hit.start()]
                assert guard in before, (
                    f"{label} calls {call} (Safari {version}) without testing for it: "
                    f"{code[max(0, hit.start() - 80):hit.end() + 20]!r}")
    assert calls >= 10, calls


def test_no_page_ships_a_module_script() -> None:
    """Every script is a classic script, so top-level await is a SyntaxError in
    every browser and the node parse below catches it. A module would need its
    own check."""
    for page in SITE.rglob("*.html"):
        assert 'type="module"' not in page.read_text(encoding="utf-8"), page


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_lexer_agrees_with_node() -> None:
    """Every regex the lexer found compiles in node, and every script with its
    strings blanked and comments dropped still parses. A lexer that split a
    script wrong would fail one of the two, so the checks above can be trusted."""
    payload = {"regexes": [t for tokens in LEXED.values() for k, t in tokens if k == "regex"],
               "scripts": {label: _code(tokens, templates=True) for label, tokens in LEXED.items()}}
    program = (
        "const vm = require('vm'); const p = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "const bad = [];"
        "for (const r of p.regexes) { try { if (!(new Function('return ' + r)() instanceof RegExp))"
        " bad.push('not a regex: ' + r); } catch (e) { bad.push(r + ': ' + e.message); } }"
        "for (const [label, src] of Object.entries(p.scripts)) { try { new vm.Script(src); }"
        " catch (e) { bad.push(label + ': ' + e.message); } }"
        "console.log(JSON.stringify(bad));")
    done = subprocess.run(["node", "-e", program], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == []
    assert len(payload["regexes"]) >= 100
