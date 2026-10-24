// The one table of commonly mistyped email domains, for every page with an
// email field: the join page (checkout, seats, updates, free reports and its
// waitlist) and the landing's waitlist capture (FUN-5). One file, so the two
// can never disagree about what counts as a typo — and never a second inline
// copy of the table on a page that loads this, because a plain <script>
// shares one global scope and declaring the table twice is a SyntaxError
// that silently stops every script on the page (b2b9dc8).
//
// It suggests; it never rewrites an address on its own (critique #1). The
// page asks "Did you mean …?" once and goes ahead with what was typed if the
// visitor says so: the address may be real. Nothing here is stored or sent.
"use strict";
// The domains people mistype most, and what they meant. Only a domain on this
// list is ever questioned, and only ever as a question.
const DOMAIN_FIXES = {
  "gmial.com": "gmail.com", "gmal.com": "gmail.com", "gmai.com": "gmail.com",
  "gamil.com": "gmail.com", "gmaill.com": "gmail.com", "gnail.com": "gmail.com",
  "gmail.co": "gmail.com", "gmail.cm": "gmail.com", "gmail.om": "gmail.com",
  "gmail.con": "gmail.com", "gmail.comm": "gmail.com", "gmali.com": "gmail.com",
  "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com", "yhoo.com": "yahoo.com",
  "yaoo.com": "yahoo.com", "yahoo.con": "yahoo.com", "yahoo.cm": "yahoo.com",
  "hotmial.com": "hotmail.com", "hotmal.com": "hotmail.com", "hotmai.com": "hotmail.com",
  "hotnail.com": "hotmail.com", "hotmail.co": "hotmail.com", "hotmail.con": "hotmail.com",
  "outlok.com": "outlook.com", "outllok.com": "outlook.com", "outlook.co": "outlook.com",
  "outlook.con": "outlook.com", "iclod.com": "icloud.com", "icoud.com": "icloud.com",
  "icloud.co": "icloud.com", "icloud.con": "icloud.com", "aol.co": "aol.com",
  "aol.con": "aol.com", "comcast.com": "comcast.net", "live.co": "live.com",
};
function suggestedEmail(email) {
  const at = email.lastIndexOf("@");
  if (at < 1) return "";
  const domain = email.slice(at + 1).toLowerCase();
  let fix = DOMAIN_FIXES[domain] || "";
  if (!fix && /\.(con|cmo|ocm|vom|comm)$/.test(domain)) {
    fix = domain.replace(/\.(con|cmo|ocm|vom|comm)$/, ".com");
  }
  return fix && fix !== domain ? email.slice(0, at + 1) + fix : "";
}
