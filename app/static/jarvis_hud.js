/* J.A.R.V.I.S. — pantalla completa de Faceless Studio.
 *
 * Estados: off (sin iniciar) → asleep (en espera) → listening ⇄ thinking ⇄ speaking.
 * - Dos palmadas (o tocar el reactor, o la barra espaciadora) lo despiertan.
 * - Escucha con el reconocimiento de voz del navegador y habla con sus voces
 *   (en Edge, las voces «Natural» suenan casi humanas). Todo gratis.
 * - Las órdenes van a /jarvis/orden: el mismo cerebro que el bot de Telegram.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const IDLE_MS = 60000; // sin hablarle 1 minuto: vuelve a dormir
  const BRIEFING_EVERY_MS = 3 * 3600 * 1000;

  // ------------------------------------------------------------ ajustes

  const defaults = { voice: "", lang: "es-CO", sens: 5, claps: true, briefing: true };
  let settings = { ...defaults };
  try { settings = { ...defaults, ...JSON.parse(localStorage.getItem("jarvis-hud") || "{}") }; } catch (e) {}
  const saveSettings = () => { try { localStorage.setItem("jarvis-hud", JSON.stringify(settings)); } catch (e) {} };
  const memory = {
    get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) {} },
  };

  // ------------------------------------------------------------ estado

  let state = "off";
  let energy = 0; // 0..1: cuánto «vibra» el reactor
  let micLevel = 0;
  let speakingPulse = 0;
  let overallProgress = 0;
  let lastActivity = Date.now();
  let pendingButtons = []; // botones de la última respuesta (para elegir con la voz)

  function setState(next, label) {
    state = next;
    const body = document.body.classList;
    [...body].filter((c) => c.startsWith("state-")).forEach((c) => body.remove(c));
    body.add("state-" + next);
    const labels = {
      asleep: settings.claps ? "EN ESPERA · 👏👏" : "EN ESPERA · TÓCAME",
      listening: "ESCUCHANDO",
      thinking: "PROCESANDO",
      speaking: "HABLANDO",
      waking: "INICIANDO",
    };
    $("state-label").textContent = label || labels[next] || "";
    if (next === "listening") lastActivity = Date.now();
  }

  // ------------------------------------------------------------ sonidos

  let audioCtx = null;

  function beep(freq, ms, delay = 0, volume = 0.06) {
    if (!audioCtx) return;
    const t = audioCtx.currentTime + delay / 1000;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, t);
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(volume, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + ms / 1000);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(t);
    osc.stop(t + ms / 1000 + 0.05);
  }
  const chimeWake = () => { beep(523, 180); beep(659, 180, 120); beep(988, 320, 240); };
  const chimeListen = () => beep(880, 120);
  const chimeSleep = () => { beep(659, 160); beep(440, 260, 120); };

  // ------------------------------------------------------------ micrófono y palmadas

  let analyser = null;
  let samples = null;
  let noiseFloor = 0.01;
  let claps = [];
  let quietUntil = 0; // tras hablar JARVIS, ignora un momento (su propia voz)

  const clapThreshold = () => 0.75 - settings.sens * 0.06; // sens 1 → 0.69 … 10 → 0.15

  async function initMic() {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") await audioCtx.resume();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: false },
    });
    const source = audioCtx.createMediaStreamSource(stream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 1024;
    samples = new Float32Array(analyser.fftSize);
    source.connect(analyser);
  }

  function listenForClaps(now) {
    if (!analyser) return;
    analyser.getFloatTimeDomainData(samples);
    let peak = 0, sum = 0;
    for (let i = 0; i < samples.length; i++) {
      const v = Math.abs(samples[i]);
      if (v > peak) peak = v;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / samples.length);
    micLevel = micLevel * 0.6 + peak * 0.4;
    $("mic-level").style.width = Math.min(100, peak * 100) + "%";

    const threshold = clapThreshold();
    const impulsive = peak > threshold && peak / Math.max(rms, 1e-4) > 3 && rms > noiseFloor * 4;
    if (!impulsive) noiseFloor = noiseFloor * 0.995 + rms * 0.005;
    if (!settings.claps || state === "speaking" || state === "off" || now < quietUntil) return;
    const last = claps[claps.length - 1] || 0;
    if (impulsive && now - last > 120) {
      claps = claps.filter((t) => now - t < 1000);
      claps.push(now);
      $("clap-dots").classList.add("on");
      setTimeout(() => $("clap-dots").classList.remove("on"), 250);
      if (claps.length >= 2) {
        const gap = claps[claps.length - 1] - claps[claps.length - 2];
        if (gap > 120 && gap < 900) {
          claps = [];
          onDoubleClap();
        }
      }
    }
  }

  function onDoubleClap() {
    if (state === "asleep") wake();
    else if (state === "listening") { chimeListen(); lastActivity = Date.now(); }
  }

  // ------------------------------------------------------------ voz de JARVIS

  let voices = [];

  function loadVoices() {
    voices = ("speechSynthesis" in window ? speechSynthesis.getVoices() : []).filter((v) => v.lang.toLowerCase().startsWith("es"));
    const score = (v) => (/natural|online|neural/i.test(v.name) ? 0 : 10) + (/male|jorge|alvaro|gonzalo|raul|pablo|dario|jorge|tomas|andres/i.test(v.name) ? 0 : 1);
    voices.sort((a, b) => score(a) - score(b));
    if (voicePrefs.engine === "browser") fillVoiceSelect();
  }

  function plain(html) {
    const div = document.createElement("div");
    div.innerHTML = html;
    return div.innerText
      .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{20E3}]/gu, "")
      .replace(/«|»/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function chunks(text) {
    const parts = text.match(/[^.!?;:\n]+[.!?;:]?/g) || [text];
    const out = [];
    let current = "";
    for (const p of parts) {
      if ((current + p).length > 180 && current) { out.push(current.trim()); current = ""; }
      current += p;
    }
    if (current.trim()) out.push(current.trim());
    return out;
  }

  // ---- Voz neuronal (la genera el programa) con el «efecto JARVIS»

  let voicePrefs = { engine: "microsoft", voice: "", effect: "jarvis", telegram: true };
  let voiceOptions = { microsoft: [], eleven: [] };
  let player = null; // un único <audio> conectado al analizador (para que el reactor «hable»)
  let voiceAnalyser = null;
  let voiceSamples = null;
  let stopSpeaking = () => {};

  function ensurePlayer() {
    if (player) return;
    player = new Audio();
    if (audioCtx) {
      const src = audioCtx.createMediaElementSource(player);
      voiceAnalyser = audioCtx.createAnalyser();
      voiceAnalyser.fftSize = 512;
      voiceSamples = new Float32Array(voiceAnalyser.fftSize);
      src.connect(voiceAnalyser);
      voiceAnalyser.connect(audioCtx.destination);
    }
  }

  function voiceLevel() {
    if (!voiceAnalyser || !player || player.paused) return 0;
    voiceAnalyser.getFloatTimeDomainData(voiceSamples);
    let sum = 0;
    for (const v of voiceSamples) sum += v * v;
    return Math.min(1, Math.sqrt(sum / voiceSamples.length) * 5);
  }

  async function fetchVoice(text) {
    const r = await fetch("/jarvis/voz", { method: "POST", body: new URLSearchParams({ text }) });
    if (!r.ok) {
      let info = {};
      try { info = await r.json(); } catch (e) {}
      throw new Error(info.error || "Sin voz");
    }
    return URL.createObjectURL(await r.blob());
  }

  function playUrl(url) {
    return new Promise((resolve) => {
      player.onended = player.onerror = () => { URL.revokeObjectURL(url); resolve(); };
      player.src = url;
      player.play().catch(() => resolve());
    });
  }

  // La primera frase sola (empieza a hablar antes) y el resto junto.
  function voiceParts(text) {
    const parts = chunks(text);
    if (parts.length <= 1) return parts;
    return [parts[0], parts.slice(1).join(" ")];
  }

  async function speak(text) {
    text = plain(text);
    if (!text) return;
    if (voicePrefs.engine === "browser") return speakBrowser(text);
    stopListening();
    setState("speaking");
    ensurePlayer();
    let cancelled = false;
    stopSpeaking = () => { cancelled = true; player.pause(); player.onended && player.onended(); };
    const parts = voiceParts(text);
    try {
      let next = fetchVoice(parts[0]);
      for (let i = 0; i < parts.length && !cancelled; i++) {
        const url = await next;
        if (i + 1 < parts.length) next = fetchVoice(parts[i + 1]); // prepara la siguiente
        await playUrl(url);
      }
    } catch (e) {
      $("voice-note").textContent = "No se pudo usar la voz neuronal (" + e.message + "). Uso la del navegador.";
      if (!cancelled) await speakBrowser(text);
    }
    quietUntil = performance.now() + 700;
  }

  function speakBrowser(text) {
    return new Promise((resolve) => {
      text = plain(text);
      if (!text || !("speechSynthesis" in window)) return resolve();
      stopSpeaking = () => speechSynthesis.cancel();
      stopListening();
      setState("speaking");
      speechSynthesis.cancel();
      const voice = voices.find((v) => v.name === settings.voice) || voices[0];
      const pieces = chunks(text);
      let left = pieces.length;
      const done = () => {
        if (--left > 0) return;
        quietUntil = performance.now() + 700;
        resolve();
      };
      for (const piece of pieces) {
        const u = new SpeechSynthesisUtterance(piece);
        u.lang = voice ? voice.lang : "es-ES";
        if (voice) u.voice = voice;
        u.rate = 1.02;
        u.pitch = 0.95;
        u.onboundary = () => { speakingPulse = 1; };
        u.onend = done;
        u.onerror = done;
        speechSynthesis.speak(u);
      }
      // Seguridad: si el navegador no habla (sin voces), no se queda colgado.
      setTimeout(() => { if (left > 0 && !speechSynthesis.speaking) { left = 1; done(); } }, 4000);
    });
  }

  // ------------------------------------------------------------ escuchar

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognizer = null;

  function listen(silent) {
    if (!silent) { // al reanudar tras un silencio no se repite el pitido ni se reinicia el reloj
      setState("listening");
      chimeListen();
    }
    if (!Recognition) {
      $("heard").textContent = "Este navegador no entiende la voz: escríbeme abajo (mejor usa Edge o Chrome).";
      return;
    }
    stopListening();
    const rec = new Recognition();
    recognizer = rec;
    rec.lang = settings.lang || "es-CO";
    rec.interimResults = true;
    rec.continuous = false;
    let finalText = "";
    rec.onresult = (e) => {
      lastActivity = Date.now();
      let text = "";
      for (const r of e.results) text += r[0].transcript;
      $("heard").textContent = "«" + text + "»";
      if (e.results[e.results.length - 1].isFinal) finalText = text;
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        $("heard").textContent = "No tengo permiso para el micrófono. Pulsa el candado de arriba y permítelo.";
      } else if (e.error === "network") {
        $("heard").textContent = "El reconocimiento de voz necesita internet.";
      }
    };
    rec.onend = () => {
      if (recognizer !== rec) return;
      recognizer = null;
      if (finalText) handle(finalText);
      else if (state === "listening") {
        if (Date.now() - lastActivity > IDLE_MS) goToSleep("Me quedo en espera. Aplaude dos veces si me necesitas.");
        else setTimeout(() => { if (state === "listening" && !recognizer) listen(true); }, 250);
      }
    };
    try { rec.start(); } catch (e) {}
  }

  function stopListening() {
    if (recognizer) {
      const r = recognizer;
      recognizer = null;
      try { r.abort(); } catch (e) {}
    }
  }

  // ------------------------------------------------------------ hablar con el cerebro

  const NUMBERS = { uno: 1, una: 1, primero: 1, primera: 1, dos: 2, segundo: 2, segunda: 2, tres: 3, tercero: 3, tercera: 3 };

  function choiceFromSpeech(text) {
    if (!pendingButtons.length) return null;
    const t = text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").trim();
    if (/elige tu|escoge tu|decide tu|el que quieras|sorprendeme/.test(t)) {
      return pendingButtons.find((b) => b.data.endsWith(":auto")) || null;
    }
    const m = t.match(/^(?:el |la |opcion |numero |enfoque )*(\d|uno|una|dos|tres|primero|primera|segundo|segunda|tercero|tercera)\b/);
    if (!m) return null;
    const n = NUMBERS[m[1]] || parseInt(m[1], 10);
    return pendingButtons.find((b) => b.data.startsWith("pick:") && b.data.endsWith(":" + (n - 1))) || null;
  }

  async function handle(text, button) {
    lastActivity = Date.now();
    if (!button) {
      const choice = choiceFromSpeech(text);
      if (choice) { button = choice.data; text = ""; }
    }
    if (text) $("heard").textContent = "«" + text + "»";
    setState("thinking");
    let data;
    try {
      const body = new URLSearchParams({ text: text || "", button: button || "" });
      const r = await fetch("/jarvis/orden", { method: "POST", body });
      if (r.redirected || r.status === 401) { location.href = "/entrar"; return; }
      data = await r.json();
    } catch (e) {
      await speak("No puedo conectar con el estudio. ¿Sigue abierta la ventana negra?");
      return goToSleep();
    }
    const replies = data.replies || [];
    showReplies(replies);
    for (const r of replies) {
      if (r.action && r.action.startsWith("open:")) window.open(r.action.slice(5), "_blank");
    }
    refresh();
    const spoken = replies.map((r) => r.html).join(". ");
    const long = plain(spoken).length > 700;
    await speak(long ? replies[0].html.split("\n")[0] + ". Te dejo el resto en pantalla." : spoken);
    if (replies.some((r) => r.action === "sleep")) goToSleep();
    else listen();
  }

  function showReplies(replies) {
    $("caption").innerHTML = replies.map((r) => r.html).join("\n\n");
    // Respuestas largas (noticias, canal…): el reactor se encoge para dejar sitio al texto.
    document.body.classList.toggle("long-answer", $("caption").innerText.length > 160);
    const box = $("choices");
    box.innerHTML = "";
    pendingButtons = [];
    replies.forEach((r) => (r.buttons || []).forEach((row) => row.forEach((b) => {
      pendingButtons.push(b);
      const btn = document.createElement("button");
      btn.textContent = b.text;
      btn.onclick = () => { if (audioCtx) handle("", b.data); };
      box.appendChild(btn);
    })));
    replies.filter((r) => r.video).forEach((r) => {
      const link = document.createElement("button");
      link.textContent = "▶ Ver el avance";
      link.onclick = () => window.open(r.video, "_blank");
      box.appendChild(link);
    });
  }

  // ------------------------------------------------------------ despertar y dormir

  async function wake() {
    if (state !== "asleep") return;
    setState("waking");
    chimeWake();
    energy = 1;
    const name = window.JARVIS_NAME ? ", " + window.JARVIS_NAME : "";
    const last = parseInt(memory.get("jarvis-last-briefing") || "0", 10);
    let text = `A sus órdenes${name}. ¿En qué le ayudo?`;
    if (settings.briefing && Date.now() - last > BRIEFING_EVERY_MS) {
      try {
        const r = await fetch("/jarvis/hud/saludo");
        text = (await r.json()).text + " ¿En qué le ayudo?";
        memory.set("jarvis-last-briefing", String(Date.now()));
      } catch (e) {}
    }
    $("caption").textContent = text;
    document.body.classList.toggle("long-answer", text.length > 160);
    $("choices").innerHTML = "";
    await speak(text);
    listen();
  }

  function goToSleep(message) {
    stopListening();
    const finish = () => { setState("asleep"); chimeSleep(); };
    if (message) speak(message).then(finish);
    else finish();
  }

  // ------------------------------------------------------------ datos en pantalla

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const KIND_ICON = { error: "⚠️", choice: "🧭", review: "🎥", upload: "🚀" };

  function renderData(d) {
    const prod = d.production || [];
    $("prod-count").textContent = prod.length ? prod.length + " EN COLA" : "";
    $("production").innerHTML = prod.length
      ? prod.map((j) => `
        <div class="job ${j.running ? "running" : ""}">
          <div class="job-title">${esc(j.project)}</div>
          <div class="job-stage"><span>${esc(j.stage)} · ${esc(j.message)}</span><span>${j.progress}%</span></div>
          <div class="bar ${j.running ? "" : "queued"}"><div style="width:${j.running ? j.progress : 100}%"></div></div>
        </div>`).join("")
      : '<div class="muted">Sin vídeos en marcha. Dime «hazme un vídeo sobre…»</div>';
    const running = prod.find((j) => j.running);
    overallProgress = running ? running.progress / 100 : 0;

    const studio = d.studio_tasks || [];
    const mine = d.tasks || [];
    const pending = studio.length + mine.filter((t) => !t.done).length;
    $("task-count").textContent = pending ? pending + " PENDIENTES" : "TODO LISTO";
    $("tasks").innerHTML =
      studio.map((t) => `<li><span class="kind">${KIND_ICON[t.kind] || "🎬"}</span><a href="${esc(t.link)}" target="_blank">${esc(t.text)}</a></li>`).join("") +
      mine.map((t) => `<li class="${t.done ? "done" : ""}"><button class="box" data-done="${t.id}" title="Hecha"></button><span>${esc(t.text)}</span><button class="del" data-del="${t.id}" title="Borrar">✕</button></li>`).join("") ||
      '<li class="muted">Nada pendiente. 😎</li>';

    const pilot = d.pilot || { queue: [] };
    $("pilot-state").textContent = pilot.on ? `ENCENDIDO · ${pilot.hour}:00` : "APAGADO";
    $("pilot").innerHTML = pilot.queue.length
      ? pilot.queue.map((t) => `<li>${esc(t)}</li>`).join("")
      : '<li class="muted" style="list-style:none;margin-left:-20px">Cola vacía. Di «cola: Nokia, Kodak»</li>';

    const sys = d.system || {};
    for (const key of ["cpu", "ram", "disk"]) {
      const g = document.querySelector(`.gauge[data-key=${key}]`);
      const v = sys[key];
      g.querySelector("b").textContent = v == null ? "--" : v + "%";
      g.querySelector(".value").style.strokeDashoffset = 264 - 264 * ((v || 0) / 100);
      g.classList.toggle("hot", (v || 0) >= 85);
    }
    $("disk-free").textContent = sys.disk_free_gb != null ? `${sys.disk_free_gb} GB LIBRES` : "";
    $("telegram-state").textContent = d.telegram ? "TELEGRAM ✓" : "TELEGRAM ✗";

    lastReminders = d.reminders || [];
    renderReminders();
    announceAlerts(d.alerts || []);
  }

  let lastReminders = [];
  function renderReminders() {
    const reminders = lastReminders;
    $("reminder-count").textContent = reminders.length ? reminders.length + " ACTIVOS" : "";
    $("reminders").innerHTML = reminders.length
      ? reminders.map((r) => `<li><span class="when">${r.kind === "timer" ? "⏱ " + countdown(r.at) : "⏰ " + timeOf(r.at)}</span>
          <span>${esc(r.text)}</span><button class="del" data-unremind="${r.id}" title="Cancelar">✕</button></li>`).join("")
      : '<li class="muted">Di «recuérdame a las 5…» o «temporizador de 10 minutos»</li>';
  }

  function timeOf(iso) {
    const d = new Date(iso);
    const today = new Date().toDateString() === d.toDateString();
    return (today ? "" : "mañ. ") + d.getHours() + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  function countdown(iso) {
    const left = Math.max(0, Math.round((new Date(iso) - Date.now()) / 1000));
    const m = Math.floor(left / 60), sec = left % 60;
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(sec).padStart(2, "0")}`;
  }

  // ------------------------------------------------------------ recordatorios que suenan

  let announced = new Set();
  try { announced = new Set(JSON.parse(memory.get("jarvis-announced") || "[]")); } catch (e) {}
  let alertQueue = [];
  let alerting = false;

  function announceAlerts(alerts) {
    for (const a of alerts) {
      const key = a.id + "@" + a.at;
      if (announced.has(key)) continue;
      announced.add(key);
      alertQueue.push(a);
    }
    memory.set("jarvis-announced", JSON.stringify([...announced].slice(-100)));
    if (!alerting && alertQueue.length && state !== "off") nextAlert();
  }

  async function nextAlert() {
    const a = alertQueue.shift();
    if (!a) { alerting = false; return; }
    alerting = true;
    const wasAsleep = state === "asleep";
    stopListening();
    $("alert-kind").textContent = a.kind === "timer" ? "TEMPORIZADOR" : "RECORDATORIO";
    $("alert-text").textContent = a.text;
    $("alert").hidden = false;
    for (let i = 0; i < 3; i++) { beep(988, 160, i * 350, 0.12); beep(1318, 160, i * 350 + 170, 0.12); }
    await new Promise((r) => setTimeout(r, 1200));
    const name = window.JARVIS_NAME ? ", " + window.JARVIS_NAME : "";
    await speak(a.kind === "timer" ? `${a.text} terminado${name}.` : `Disculpe${name}. Le recuerdo: ${a.text}.`);
    setTimeout(() => { $("alert").hidden = true; }, 6000);
    if (alertQueue.length) return nextAlert();
    alerting = false;
    if (wasAsleep) setState("asleep");
    else listen();
  }
  $("alert-ok").addEventListener("click", () => { $("alert").hidden = true; });
  $("reminders").addEventListener("click", async (e) => {
    const id = e.target.dataset.unremind;
    if (!id) return;
    try { await fetch(`/jarvis/recordatorios/${id}/borrar`, { method: "POST" }); } catch (err) {}
    refresh();
  });

  // ------------------------------------------------------------ el mundo (internet)

  const num = (n) => Number(n).toLocaleString("es-CO");

  function renderWorld(w) {
    const now = w.weather;
    if (now) {
      $("weather").innerHTML = `<div class="label">${esc(now.city)}</div><div class="weather-temp">${now.temp}°</div>
        <div class="label">${esc(now.sky)} · ${now.min}° / ${now.max}°${now.rain >= 30 ? " · ☔ " + now.rain + "%" : ""}</div>`;
    }
    $("forecast").innerHTML = (w.forecast || []).slice(1).map((f) =>
      `<span>${esc(f.day)} <b>${f.min}°/${f.max}°</b>${f.rain >= 40 ? " ☔" : ""}</span>`).join("");
    $("dollar").textContent = w.dollar ? `USD → ${w.dollar.currency}: ${num(w.dollar.rate)}` : "";

    const yt = w.youtube;
    if (yt) {
      $("channel-name").textContent = yt.exact ? "EN VIVO" : "APROX.";
      const subs = yt.subscribers != null ? num(yt.subscribers) : "—";
      const goal = yt.goal_pct != null
        ? `<div class="goal"><div class="job-stage"><span>Meta para monetizar: ${num(yt.goal)}</span><span>${yt.goal_pct}%</span></div>
           <div class="bar"><div style="width:${yt.goal_pct}%"></div></div></div>` : "";
      const stats = [
        yt.videos ? `<span><b>${num(yt.videos)}</b> vídeos</span>` : "",
        yt.views && yt.exact ? `<span><b>${num(yt.views)}</b> visitas</span>` : "",
      ].join("");
      const latest = (yt.latest || []).slice(0, 3).map((v) =>
        `<li><a href="${esc(v.url)}" target="_blank" title="${esc(v.title)}">${esc(v.title)}</a><span>👁 ${num(v.views)}</span></li>`).join("");
      $("channel").innerHTML = `<div class="subs"><b>${subs}</b><span class="label">SUSCRIPTORES</span></div>
        ${goal}<div class="stat-row">${stats}</div><ul class="latest">${latest}</ul>`;
    } else {
      $("channel").innerHTML = '<div class="muted small">No pude leer el canal. Revisa el nombre en la página JARVIS.</div>';
    }

    const items = [
      ...(w.radar || []).map((n) => ({ ...n, hot: true })),
      ...(w.news || []),
    ];
    if (items.length) {
      const html = items.map((n) => `<a href="${esc(n.url)}" target="_blank">${n.hot ? '<span class="hot">●</span>' : ""}${esc(n.title)}<span class="src">${esc(n.source)}</span></a>`).join("");
      $("ticker-track").innerHTML = html + html; // dos veces para que el bucle no tenga saltos
    } else {
      $("ticker-track").textContent = "Sin noticias por ahora (¿hay internet?).";
    }

    if (w.fact) {
      $("fact").hidden = false;
      $("fact").querySelector("p").textContent = w.fact;
    }
  }

  async function refreshWorld() {
    try {
      const r = await fetch("/jarvis/hud/mundo");
      if (r.redirected) return;
      renderWorld(await r.json());
    } catch (e) {}
  }

  async function refresh() {
    try {
      const r = await fetch("/jarvis/hud/datos");
      if (r.redirected) { location.href = "/entrar"; return; }
      renderData(await r.json());
    } catch (e) {}
  }

  async function taskAction(url, body) {
    try {
      await fetch(url, { method: "POST", body: body ? new URLSearchParams(body) : undefined });
    } catch (e) {}
    refresh();
  }

  $("tasks").addEventListener("click", (e) => {
    const done = e.target.dataset.done;
    const del = e.target.dataset.del;
    if (done) taskAction(`/jarvis/tareas/${done}/hecha`);
    if (del) taskAction(`/jarvis/tareas/${del}/borrar`);
  });
  $("task-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("task-input").value.trim();
    $("task-input").value = "";
    if (text) taskAction("/jarvis/tareas", { text });
  });
  $("type-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("type-input").value.trim();
    $("type-input").value = "";
    if (text && state !== "off") handle(text);
  });

  // ------------------------------------------------------------ reloj

  const DAYS = ["DOMINGO", "LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO"];
  const MONTHS = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"];
  function tickClock() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    $("clock").firstChild.nodeValue = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    $("seconds").textContent = pad(d.getSeconds());
    $("date").textContent = `${DAYS[d.getDay()]} · ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  }

  // ------------------------------------------------------------ animación

  const reactor = $("reactor");
  const ctx = reactor.getContext("2d");
  const bg = $("bg");
  const bgx = bg.getContext("2d");
  const particles = Array.from({ length: 70 }, () => ({ x: Math.random(), y: Math.random(), v: 0.0002 + Math.random() * 0.0006, r: Math.random() * 1.6 }));

  function drawBackground(t) {
    const w = (bg.width = innerWidth), h = (bg.height = innerHeight);
    bgx.clearRect(0, 0, w, h);
    bgx.strokeStyle = "rgba(127,216,255,0.045)";
    bgx.lineWidth = 1;
    const step = 48;
    const off = (t / 80) % step;
    bgx.beginPath();
    for (let x = -step + off; x < w; x += step) { bgx.moveTo(x, 0); bgx.lineTo(x, h); }
    for (let y = -step + off; y < h; y += step) { bgx.moveTo(0, y); bgx.lineTo(w, y); }
    bgx.stroke();
    bgx.fillStyle = "rgba(127,216,255,0.5)";
    for (const p of particles) {
      p.y -= p.v * (state === "asleep" ? 0.5 : 1.5);
      if (p.y < 0) { p.y = 1; p.x = Math.random(); }
      bgx.beginPath();
      bgx.arc(p.x * w, p.y * h, p.r, 0, Math.PI * 2);
      bgx.fill();
    }
  }

  function ring(r, width, start, length, color, dash) {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.setLineDash(dash || []);
    ctx.arc(0, 0, r, start, start + length);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawReactor(t) {
    const W = reactor.width, c = W / 2;
    ctx.clearRect(0, 0, W, W);
    ctx.save();
    ctx.translate(c, c);
    const asleep = state === "asleep" || state === "off";
    const alpha = asleep ? 0.45 : 1;
    const speed = asleep ? 0.25 : state === "thinking" ? 3 : 1;
    const voice = voiceLevel();
    if (voice) speakingPulse = Math.max(speakingPulse, voice);
    const target = state === "speaking" ? 0.35 + speakingPulse * 0.6 : state === "listening" ? Math.min(1, micLevel * 3) : asleep ? 0.05 : 0.25;
    energy += (target - energy) * 0.15;
    speakingPulse *= 0.9;
    const cyan = (a) => `rgba(127,216,255,${a * alpha})`;
    const red = (a) => `rgba(230,57,70,${a * alpha})`;
    const s = t / 1000;

    // Brillo de fondo
    const glow = ctx.createRadialGradient(0, 0, 10, 0, 0, c * 0.95);
    glow.addColorStop(0, cyan(0.25 + energy * 0.35));
    glow.addColorStop(0.35, cyan(0.06));
    glow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(-c, -c, W, W);

    // Anillo exterior con marcas
    ctx.save();
    ctx.rotate(s * 0.05 * speed);
    for (let i = 0; i < 120; i++) {
      const a = (i / 120) * Math.PI * 2;
      const long = i % 10 === 0;
      ctx.strokeStyle = cyan(long ? 0.8 : 0.3);
      ctx.lineWidth = long ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a) * (c * 0.9), Math.sin(a) * (c * 0.9));
      ctx.lineTo(Math.cos(a) * (c * (long ? 0.84 : 0.87)), Math.sin(a) * (c * (long ? 0.84 : 0.87)));
      ctx.stroke();
    }
    ctx.restore();

    // Progreso de la producción (arco rojo)
    ring(c * 0.8, 4, -Math.PI / 2, Math.PI * 2, cyan(0.1));
    if (overallProgress > 0) ring(c * 0.8, 4, -Math.PI / 2, Math.PI * 2 * overallProgress, red(0.9));

    // Segmentos que giran
    ctx.save();
    ctx.rotate(-s * 0.4 * speed);
    for (let i = 0; i < 6; i++) ring(c * 0.7, 10, (i / 6) * Math.PI * 2, Math.PI / 5, cyan(0.55));
    ctx.restore();
    ctx.save();
    ctx.rotate(s * 0.7 * speed);
    ring(c * 0.6, 2, 0, Math.PI * 1.4, cyan(0.8));
    ring(c * 0.6, 2, Math.PI * 1.55, Math.PI * 0.3, red(0.8));
    ctx.restore();
    ctx.save();
    ctx.rotate(-s * 1.2 * speed);
    ring(c * 0.52, 1, 0, Math.PI * 2, cyan(0.5), [4, 10]);
    ctx.restore();

    // Ondas de voz alrededor del núcleo
    ctx.beginPath();
    const bars = 64;
    for (let i = 0; i < bars; i++) {
      const a = (i / bars) * Math.PI * 2;
      const wave = Math.sin(a * 6 + s * 6) * 0.5 + Math.sin(a * 11 - s * 9) * 0.5;
      const len = 6 + energy * 40 * (0.6 + 0.4 * wave);
      const r0 = c * 0.36;
      ctx.moveTo(Math.cos(a) * r0, Math.sin(a) * r0);
      ctx.lineTo(Math.cos(a) * (r0 + len), Math.sin(a) * (r0 + len));
    }
    ctx.strokeStyle = cyan(0.7);
    ctx.lineWidth = 3;
    ctx.stroke();

    // Núcleo
    const breathe = asleep ? 0.5 + 0.5 * Math.sin(s * 1.5) : 1;
    const coreR = c * (0.22 + energy * 0.06);
    const core = ctx.createRadialGradient(0, 0, 0, 0, 0, coreR);
    core.addColorStop(0, `rgba(240,252,255,${(0.6 + 0.4 * breathe) * alpha})`);
    core.addColorStop(0.45, cyan(0.75 * breathe + 0.2));
    core.addColorStop(1, "rgba(127,216,255,0)");
    ctx.fillStyle = core;
    ctx.beginPath();
    ctx.arc(0, 0, coreR, 0, Math.PI * 2);
    ctx.fill();
    // Triángulo interior (como el reactor de la armadura)
    ctx.save();
    ctx.rotate(s * 0.2 * speed);
    ctx.strokeStyle = cyan(0.6);
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < 3; i++) {
      const a = (i / 3) * Math.PI * 2 - Math.PI / 2;
      const p = [Math.cos(a) * c * 0.17, Math.sin(a) * c * 0.17];
      i ? ctx.lineTo(...p) : ctx.moveTo(...p);
    }
    ctx.closePath();
    ctx.stroke();
    ctx.restore();
    ctx.restore();
  }

  function frame(t) {
    listenForClaps(performance.now());
    drawReactor(t);
    drawBackground(t);
    $("mic-threshold").style.left = Math.min(100, clapThreshold() * 100) + "%";
    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------ arranque

  async function boot() {
    const lines = ["INICIANDO SISTEMAS…", "CONECTANDO CON FACELESS STUDIO…", "CALIBRANDO MICRÓFONO…"];
    const box = $("boot-lines");
    box.textContent = "";
    $("boot-button").hidden = true;
    for (const line of lines) {
      box.textContent += line + "\n";
      await new Promise((r) => setTimeout(r, 380));
    }
    try {
      await initMic();
      box.textContent += "MICRÓFONO ✓\n";
    } catch (e) {
      box.textContent += "SIN MICRÓFONO: tócame o escribe para hablar conmigo.\n";
      settings.claps = false;
    }
    await new Promise((r) => setTimeout(r, 400));
    $("boot").hidden = true;
    setState("asleep");
    wake();
  }

  $("boot-button").addEventListener("click", boot);

  // Si el navegador ya permite sonido y micrófono (JARVIS.bat lo abre así), arranca solo.
  (async () => {
    try {
      const mic = await navigator.permissions.query({ name: "microphone" });
      const test = new (window.AudioContext || window.webkitAudioContext)();
      if (mic.state === "granted" && test.state === "running") {
        audioCtx = test;
        boot();
      } else {
        test.close();
      }
    } catch (e) {}
  })();
  reactor.addEventListener("click", () => {
    if (state === "asleep") wake();
    else if (state === "speaking") stopSpeaking();
    else if (state === "listening") chimeListen();
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.code === "Space") {
      e.preventDefault();
      if (state === "asleep") wake();
      else if (state === "speaking") stopSpeaking();
    }
    if (e.key === "Escape") $("settings").hidden = true;
  });
  $("btn-full").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch(() => {});
  });

  // Ajustes
  $("btn-settings").addEventListener("click", () => {
    $("set-lang").value = settings.lang;
    $("set-sens").value = settings.sens;
    $("set-claps").checked = settings.claps;
    $("set-briefing").checked = settings.briefing;
    $("settings").hidden = false;
  });
  $("settings-close").addEventListener("click", () => ($("settings").hidden = true));
  function fillVoiceSelect() {
    const select = $("set-voice");
    let options = [];
    if (voicePrefs.engine === "microsoft") options = voiceOptions.microsoft.map((v) => [v.id, v.label]);
    if (voicePrefs.engine === "eleven") options = voiceOptions.eleven.map((v) => [v.id, v.label]);
    if (voicePrefs.engine === "browser") options = voices.map((v) => [v.name, `${v.name} (${v.lang})`]);
    select.innerHTML = options.map(([id, label]) => `<option value="${esc(id)}">${esc(label)}</option>`).join("")
      || `<option value="">${voicePrefs.engine === "eleven" ? "Conecta ElevenLabs en Configuración" : "Sin voces"}</option>`;
    select.value = voicePrefs.engine === "browser" ? settings.voice : voicePrefs.voice;
    if (!select.value && options.length) select.value = options[0][0];
    $("set-effect").disabled = voicePrefs.engine === "browser";
  }

  async function loadVoiceOptions() {
    try {
      const r = await fetch("/jarvis/voz/opciones");
      const data = await r.json();
      voicePrefs = data.prefs;
      voiceOptions = data;
      $("set-engine").value = voicePrefs.engine;
      $("set-effect").value = voicePrefs.effect;
      $("set-telegram").checked = voicePrefs.telegram;
      $("voice-note").textContent = data.eleven_error ? "ElevenLabs: " + data.eleven_error : "";
      fillVoiceSelect();
    } catch (e) {}
  }

  async function saveVoicePrefs() {
    const voice = $("set-voice").value;
    if (voicePrefs.engine === "browser") { settings.voice = voice; saveSettings(); }
    const body = new URLSearchParams({
      engine: voicePrefs.engine,
      voice: voicePrefs.engine === "browser" ? "" : voice,
      effect: $("set-effect").value,
      telegram_voice: $("set-telegram").checked ? "1" : "0",
    });
    try {
      const r = await fetch("/jarvis/voz/preferencias", { method: "POST", body });
      voicePrefs = await r.json();
    } catch (e) {}
  }

  $("set-engine").addEventListener("change", (e) => { voicePrefs.engine = e.target.value; fillVoiceSelect(); saveVoicePrefs(); });
  $("set-voice").addEventListener("change", saveVoicePrefs);
  $("set-effect").addEventListener("change", saveVoicePrefs);
  $("set-telegram").addEventListener("change", saveVoicePrefs);
  loadVoiceOptions();
  if ("speechSynthesis" in window) {
    loadVoices();
    speechSynthesis.onvoiceschanged = loadVoices;
  }
  $("set-lang").addEventListener("change", (e) => { settings.lang = e.target.value; saveSettings(); });
  $("set-sens").addEventListener("input", (e) => { settings.sens = parseInt(e.target.value, 10); saveSettings(); });
  $("set-claps").addEventListener("change", (e) => { settings.claps = e.target.checked; saveSettings(); setState(state); });
  $("set-briefing").addEventListener("change", (e) => { settings.briefing = e.target.checked; saveSettings(); });
  $("set-test").addEventListener("click", () => {
    const previous = state;
    speak("Hola. Soy JARVIS, su asistente de producción. Todos los sistemas funcionan.").then(() => {
      setState(previous);
      if (previous === "listening") listen(true);
    });
  });

  tickClock();
  setInterval(tickClock, 1000);
  refresh();
  setInterval(refresh, 5000);
  refreshWorld();
  setInterval(refreshWorld, 120000);
  setInterval(() => { // los temporizadores cuentan cada segundo
    if (lastReminders.some((r) => r.kind === "timer")) renderReminders();
  }, 1000);
  requestAnimationFrame(frame);
})();
