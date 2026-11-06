# Faceless Studio — guía para Claude

## Quién lo usa y cómo hablarle
- Lo usan Simón y su mejor amigo (2 cuentas) en un PC con **Windows**. Canal de YouTube:
  **«Anatomía De Una Marca»** (@AnatomiaDeUnaMarca), documentales sobre marcas y empresas
  que suben y caen.
- Simón es **principiante**, trabaja en cocina y tiene poco tiempo: respóndele en
  **español sencillo**, con pasos numerados, sin jerga, y di qué botón pulsar.
- Presupuesto mínimo: Gemini (nivel gratuito), ElevenLabs (opcional), Google Flow (imágenes
  gratis, a mano) y voces de Microsoft gratis. No proponer servicios de pago sin avisar.
- Nada se publica en YouTube sin su visto bueno (protege la monetización). Recomendar la
  etiqueta de contenido sintético cuando haya imágenes de IA.

## Qué es
Programa local (Python 3.11+, FastAPI + Jinja2, SQLite, worker en un hilo) que hace vídeos
«faceless» de principio a fin: investigación → estrategia → guion → escenas (con gráficos
animados) → voz → visuales → montaje FFmpeg → textos SEO → 3 miniaturas → Shorts con
portada. Además: **JARVIS** (bot de Telegram + pantalla completa con voz y palmadas),
recordatorios, noticias/radar de marcas, y **Rendimiento** (cifras de YouTube y análisis).

## Mapa del código
- `app/jobs.py`: etapas (`RUNNERS`), cola persistente, reintentos, `NEXT_STAGE` (encadenado
  en modo automático), trabajador (también refresca analíticas y hace la copia diaria).
- `app/pipeline/`: research, strategy, script, storyboard, charts, voice, visuals, render,
  seo, thumbnail, shorts.
- `app/providers/`: Gemini (cadena de modelos), voces (Microsoft/ElevenLabs), imágenes
  (solo Gemini, de pago; lo gratis es Flow en `app/flow.py`), stock, búsqueda (Wikipedia).
- JARVIS: `assistant.py` (cerebro/intenciones), `skills.py`, `agenda.py`, `info.py`,
  `telegram.py`, `jarvis_voice.py`, `jarvis_web.py`, `static/jarvis_hud.*`.
- `analytics.py` + `analytics_web.py`: rendimiento. `storage.py`: dónde viven los datos.
- `updater.py` (botón Actualizar: descarga el zip de la rama `claude/hola-5p4ttp`).

## Dónde están los datos del usuario (¡importante!)
- Desde la v0.18: **`%USERPROFILE%\FacelessStudio\datos`** (base de datos `faceless.db`,
  proyectos, vídeos, claves cifradas). Fuera de la carpeta del programa y de OneDrive.
- Antes vivían en `<carpeta del programa>\datos`; `storage.migrate_legacy` los copia la
  primera vez y renombra la vieja a `datos (copiados a FacelessStudio)`.
- Copia diaria (sin vídeos) en `OneDrive\FacelessStudio-copias` o
  `FacelessStudio\copias_de_seguridad\diarias`.
- **Nunca borrar** `FacelessStudio`. Las copias viejas del programa (carpetas con
  `Iniciar.bat` sin `JARVIS.bat`, p. ej. versión 0.3.x) sí se pueden borrar cuando se
  confirme que los proyectos aparecen en la versión nueva.
- Si «se perdió todo»: casi siempre abrió **otra copia** del programa. La buena tiene
  `JARVIS.bat`; la ventana negra y Configuración muestran la carpeta de datos.

## Dónde está el programa (desde la v0.24)
- Sitio fijo: **`%USERPROFILE%\FacelessStudio\programa`**, al lado de `datos`. Lo instala
  `scripts/instalar.ps1` (una línea con Windows + R; está en el README y en Configuración),
  que mueve, sin borrar, las copias viejas y los .zip a `FacelessStudio\copias_viejas` y crea
  en el escritorio «Faceless Studio», «JARVIS» y «Actualizar Faceless Studio».
- Si abre una versión vieja: casi siempre usa un acceso directo o una carpeta antigua, o la
  rama `claude/hola-5p4ttp` no tiene aún lo último. Que use el instalador.

## Reglas de trabajo
- Rama de desarrollo: `claude/hola-5p4ttp` (es la que descarga el actualizador).
- Antes de subir: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`.
- Cada versión: subir `VERSION` en `app/config.py`, `pyproject.toml` y la aserción de
  `tests/test_auth.py`; luego `uv lock`.
- CI (GitHub Actions) prueba en Ubuntu y **Windows** y ejecuta
  `scripts/comprobar_integraciones.py` con servicios reales: revisar que quede en verde.
- Windows: cerrar siempre las conexiones `sqlite3` (el `with` no cierra el archivo),
  archivos bloqueados por antivirus/OneDrive, consola cp1252 (sin caracteres raros al
  imprimir), `.bat` con finales de línea CRLF.
- Los tests nunca usan internet (ver `tests/conftest.py`): simular proveedores.
- Comentarios y textos de la interfaz en español; seguir el estilo del código existente.

## Herramientas de ECC (agentes y habilidades)
Copiadas de ECC (nexolunch2026/ECC, licencia MIT en `.claude/ECC-LICENSE`), solo las útiles
para este proyecto (Python + FastAPI + Windows + vídeo):
- Agentes en `.claude/agents/`: `python-reviewer`, `fastapi-reviewer`, `security-reviewer`,
  `silent-failure-hunter`, `code-simplifier`.
- Habilidades en `.claude/skills/`: `python-patterns`, `python-testing`, `fastapi-patterns`,
  `verification-loop`, `security-review`, `content-engine` (guiones y contenido para YouTube),
  `video-editing` (FFmpeg y montaje).

Cuándo usarlos:
- Antes de subir una mejora: revisa el diff con `python-reviewer` y `silent-failure-hunter`
  (los errores escondidos ya dieron problemas en JARVIS: «No te entendí bien» tapaba fallos
  de Gemini). Corrige lo importante; lo opcional, solo si es claro.
- Si tocas la web, subidas de archivos, claves, Telegram o el instalador: también
  `security-reviewer` (y `fastapi-reviewer` para rutas y formularios).
- Al cambiar prompts de guion, títulos o Shorts: consulta `content-engine`.
- Al tocar el montaje (render, Shorts, filtros): consulta `video-editing` y prueba cada
  filtro con el ffmpeg de `imageio_ffmpeg`.
- Al terminar: `verification-loop` (ruff, formato, pytest) antes del commit.

## Skills que usamos en el día a día (desde nov 2026)
Elegidas para este proyecto entre los plugins instalados (marketing, Matt Pocock «Skills For
Real Engineers», Task Observer) y las de ECC de arriba. Úsalas sin que Simón las pida:

| Momento | Skill | Para qué |
|---|---|---|
| Elegir temas (1 vez al mes, o si un canal se estanca) | `marketing:competitive-brief` | Qué funciona en la competencia, huecos, 10 temas por canal |
| Decisiones grandes (nuevo canal, cambiar de estilo, estrategia) | `grill-me` | Preguntar de una en una hasta no dejar nada sin decidir |
| Antes de grabar cada guion | `research` | Comprobar cifras, fechas y nombres en fuentes originales (p. ej. Theranos 9.000 vs 10.000 M) |
| Gancho, títulos, descripción y Shorts | `content-engine` | Los primeros 30 s y los títulos de misterio que funcionan |
| Fallos del programa | `diagnosing-bugs` | Reproducir, aislar, arreglar y dejar un test |
| Antes de subir cambios a GitHub | `verification-loop` + `code-review` | ruff, formato, pytest y revisión del diff |
| Cuando Simón y Esteban se turnan o la sesión es larga | `handoff` | Documento con dónde quedó todo para que el otro siga |
| Al terminar un vídeo o una sesión larga | `retro` | Qué mejorar en el proceso, lo más grave primero |
| Cada semana, cuando haya vídeos con datos | `marketing:performance-report` | Qué funcionó, qué no y qué cambiar |
| Siempre (automático) | Task Observer | Cada corrección de Simón/Esteban se guarda como regla |

No usar (no aportan aquí): tickets/PR/TypeScript de Matt Pocock, ni el paquete de Addy Osmani.

## Estilo de los vídeos (desde la v0.70)
- Todo en **stickman 2D** con el mismo protagonista (`flow.STICKMAN_STYLE`); voz por defecto
  **es-MX-JorgeNeural**. Piper, Pollinations y el estilo realista se quitaron a petición de Simón.
- Imágenes gratis: **Google Flow a mano**. NUNCA automatizar la generación en Flow (Google lo
  bloquea como «actividad inusual»): el programa da los mensajes para el asistente de Flow, un
  marcador recoge los enlaces y `/visuales/flow` descarga y reparte (Gemini mira las imágenes).
