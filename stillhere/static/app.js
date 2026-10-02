// Small progressive enhancements. Every page works without this file.
(() => {
  // Pulse tooltips: hover on desktop, tap on touch.
  document.querySelectorAll("[data-pulse]").forEach((fig) => {
    const tip = fig.querySelector(".pulse-tip");
    let active = null;
    const show = (pt) => {
      active?.classList.remove("on");
      active = pt;
      pt.classList.add("on");
      const score = pt.dataset.score ? ` · ${pt.dataset.word} ${pt.dataset.score}/5` : "";
      tip.innerHTML = "";
      const b = document.createElement("b");
      b.textContent = pt.dataset.label + score;
      tip.append(b, document.createTextNode(pt.dataset.line));
      const fr = fig.getBoundingClientRect(), pr = pt.getBoundingClientRect();
      const x = Math.min(Math.max(pr.left + pr.width / 2 - fr.left, 110), fr.width - 110);
      tip.style.left = `${x}px`;
      tip.style.top = `${pr.top - fr.top + pr.height / 2}px`;
      tip.hidden = false;
    };
    const hide = () => { tip.hidden = true; active?.classList.remove("on"); active = null; };
    fig.querySelectorAll(".pt").forEach((pt) => {
      pt.addEventListener("mouseenter", () => show(pt));
      pt.addEventListener("focus", () => show(pt));
      pt.addEventListener("click", (e) => { e.stopPropagation(); active === pt ? hide() : show(pt); });
      pt.addEventListener("mouseleave", hide);
      pt.addEventListener("blur", hide);
    });
    document.addEventListener("click", hide);
  });

  // Copy buttons on the setup page.
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const input = btn.parentElement.querySelector("input");
      try { await navigator.clipboard.writeText(input.value); } catch { input.select(); document.execCommand("copy"); }
      const old = btn.textContent;
      btn.textContent = "Copied ✓";
      setTimeout(() => (btn.textContent = old), 1600);
    });
  });

  // Drop ?saved=… so a refresh doesn't replay the toast.
  if (location.search.includes("saved=")) {
    const url = new URL(location.href);
    url.searchParams.delete("saved");
    history.replaceState(null, "", url);
  }
})();
