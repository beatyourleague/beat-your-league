// Reveal-on-scroll for the paper pages (PAGES-FOUNDATION). Blocks marked
// data-reveal rise into place the first time they enter the viewport;
// data-reveal="group" staggers its children instead. It stores nothing,
// sends nothing and reads nothing but the page's own layout.
//
// Fail open, always: no IntersectionObserver, reduced motion, or no marked
// blocks, and the class that hides anything is never added — the page is
// complete without this file. A block already in view is shown in the same
// task the class goes on, so it never flashes; boxes are measured BEFORE the
// class goes on, because measuring after would compute every block hidden
// first and an in-view block would then fade in from nothing. Everything is
// shown after six seconds whatever happens, and before printing.
(function () {
  "use strict";
  if (!("IntersectionObserver" in window)) return;
  if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  var items = [].slice.call(document.querySelectorAll("[data-reveal]"));
  if (!items.length) return;
  var fold = window.innerHeight;
  var inView = items.map(function (el) { return el.getBoundingClientRect().top < fold; });
  items.forEach(function (el) {
    if (el.getAttribute("data-reveal") === "group") {
      [].slice.call(el.children).forEach(function (child, i) {
        child.style.setProperty("--d", Math.min(i, 6) * 70 + "ms");
      });
    }
  });
  document.documentElement.classList.add("motion");
  var show = function (el) { el.classList.add("in"); };
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) { show(entry.target); io.unobserve(entry.target); }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
  items.forEach(function (el, i) { if (inView[i]) show(el); else io.observe(el); });
  setTimeout(function () { items.forEach(show); }, 6000);
  window.addEventListener("beforeprint", function () { items.forEach(show); });
})();
