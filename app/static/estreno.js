// Rediseño «Estreno»: movimiento suave con GSAP + Lenis. Si no cargan (sin internet) o la
// persona pidió menos movimiento, la página queda igual de completa, solo que quieta.
(function () {
  // Filtros de la hoja de contactos (funcionan siempre, sin GSAP)
  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      const want = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach((b) => b.classList.toggle("on", b === button));
      document.querySelectorAll(".x-ct").forEach((ct) => {
        ct.hidden = want !== "all" && !ct.classList.contains(want);
      });
    });
  });

  if (!window.gsap || !window.ScrollTrigger) return;
  gsap.registerPlugin(ScrollTrigger);
  const mm = gsap.matchMedia();
  mm.add("(prefers-reduced-motion: no-preference)", () => {
    if (window.Lenis) {
      const lenis = new Lenis({ lerp: 0.1 });
      lenis.on("scroll", ScrollTrigger.update);
      gsap.ticker.add((t) => lenis.raf(t * 1000));
      gsap.ticker.lagSmoothing(0);
    }

    // Portada: las letras suben y la pantalla se endereza al bajar
    document.querySelectorAll("[data-split]").forEach((el) => {
      el.innerHTML = el.textContent.split(" ").map((word) =>
        `<span style="display:inline-block;white-space:nowrap">${[...word].map((c) => `<span style="display:inline-block">${c}</span>`).join("")}</span>`
      ).join(" ");
    });
    gsap.from("[data-split] span span", { yPercent: 60, rotate: 6, duration: .9, ease: "expo.out", stagger: .025 });
    gsap.from(".x-hero .lead, .x-hero .meta, .x-hero .cta", { y: 22, duration: .8, ease: "expo.out", stagger: .08, delay: .2 });
    const screen = document.querySelector(".x-screen");
    if (screen && matchMedia("(min-width: 901px)").matches) {
      gsap.to(screen, { rotateY: 0, rotateX: 0, ease: "none", scrollTrigger: { trigger: ".x-hero", start: "top top", end: "bottom top", scrub: true } });
      if (matchMedia("(hover: hover)").matches) {
        document.querySelector(".x-hero").addEventListener("pointermove", (e) => {
          const r = screen.getBoundingClientRect();
          const x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
          gsap.to(screen, { rotateY: -14 + x * 10, rotateX: 6 - y * 8, duration: .6, ease: "power3.out", overwrite: "auto" });
        });
      }
    }

    // Botones magnéticos (solo con ratón)
    if (matchMedia("(hover: hover)").matches) {
      document.querySelectorAll(".x-magnet").forEach((b) => {
        b.addEventListener("pointermove", (e) => {
          const r = b.getBoundingClientRect();
          gsap.to(b, { x: (e.clientX - r.left - r.width / 2) * .16, y: (e.clientY - r.top - r.height / 2) * .28, duration: .3, ease: "power3.out" });
        });
        b.addEventListener("pointerleave", () => gsap.to(b, { x: 0, y: 0, duration: .5, ease: "elastic.out(1,.4)" }));
      });
    }

    // La semana: la película se desliza en horizontal en pantallas grandes
    const film = document.querySelector(".x-film");
    if (film) {
      gsap.matchMedia().add("(min-width: 901px)", () => {
        const distance = () => Math.max(0, film.scrollWidth - film.parentElement.clientWidth + 48);
        if (distance() < 20) return;
        gsap.to(film, { x: () => -distance(), ease: "none", scrollTrigger: { trigger: ".x-film-pin", start: "top 16%", end: () => "+=" + distance(), scrub: 1, pin: true, invalidateOnRefresh: true } });
      });
    }

    // Pósters escalonados
    document.querySelectorAll(".x-posters").forEach((row) => {
      gsap.from(row.children, { y: 40, rotate: 1.2, duration: .8, ease: "expo.out", stagger: .08, scrollTrigger: { trigger: row, start: "top 85%" } });
    });

    // Claqueta: se cierra de golpe; el sello cae
    const clap = document.querySelector(".x-clap-top");
    if (clap) {
      gsap.fromTo(clap, { rotate: -22 }, { rotate: 0, duration: .45, ease: "back.out(3)", delay: .25 });
      gsap.from(".x-take", { x: -18, duration: .5, ease: "expo.out", stagger: .06, delay: .3 });
    }
    gsap.from(".x-rubber", { scale: 2.2, rotate: -30, duration: .5, ease: "back.out(2)", delay: .45 });

    // Lápiz rojo: dibuja los círculos de las escenas marcadas
    document.querySelectorAll(".x-ct svg path").forEach((p, i) => {
      const len = p.getTotalLength();
      gsap.fromTo(p, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: .8, ease: "power2.inOut", delay: Math.min(i, 8) * .18, scrollTrigger: { trigger: p.closest(".x-contacts"), start: "top 75%" } });
    });
  });
})();
