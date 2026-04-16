// bpetite docs: tiny runtime. Code-block copy, smooth anchor jumps,
// scroll-reveal animations.
// Kept pure and dependency-free so the strict CSP (script-src 'self') holds.
(() => {
  "use strict";

  const copyLabel = "copy";
  const copiedLabel = "copied";
  const errorLabel = "failed";
  const resetDelay = 1800;

  /**
   * Attach a copy button to every <pre class="code"> block.
   * The button is created at runtime so it is not visible for users
   * with JavaScript disabled (they can still select-all and copy).
   */
  const enhanceCodeBlocks = () => {
    const blocks = document.querySelectorAll("pre.code, figure.code");
    blocks.forEach((block) => {
      if (block.querySelector(".copy-btn")) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.setAttribute("aria-label", "copy code block to clipboard");
      btn.textContent = copyLabel;
      btn.addEventListener("click", async () => {
        const code = block.querySelector("code") || block.querySelector("pre");
        if (!code) return;
        const text = code.innerText.replace(/\n$/, "");
        try {
          await navigator.clipboard.writeText(text);
          btn.textContent = copiedLabel;
          btn.dataset.state = "copied";
        } catch (_err) {
          btn.textContent = errorLabel;
        }
        window.setTimeout(() => {
          btn.textContent = copyLabel;
          delete btn.dataset.state;
        }, resetDelay);
      });
      block.appendChild(btn);
    });
  };

  /**
   * Scroll-reveal: observe elements with .reveal, .reveal-delay, or
   * .reveal-stagger and add .is-visible when they enter the viewport.
   * Respects prefers-reduced-motion: if the user prefers reduced motion,
   * skip observation entirely (CSS leaves everything visible by default).
   */
  const initScrollReveal = () => {
    const prefersReduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    if (prefersReduced) return;

    const targets = document.querySelectorAll(
      ".reveal, .reveal-delay, .reveal-stagger"
    );
    if (!targets.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 }
    );

    targets.forEach((el) => observer.observe(el));
  };

  const onReady = (fn) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  };

  onReady(() => {
    enhanceCodeBlocks();
    initScrollReveal();
  });
})();
