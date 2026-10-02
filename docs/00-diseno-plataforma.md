# Plataforma de producción Faceless para YouTube — Documento de diseño

> Estado: **v0.5** — investigación, estrategia, guion, escenas y voz.
>
> **Cambio v0.3 (prioriza la sencillez de instalación):** el usuario es principiante y
> usa Windows, así que se sustituye la pila con Docker por una app que arranca con
> doble clic (`Iniciar.bat` → `uv run python -m app`):
>
> | Antes (v0.2) | Ahora (v0.3) |
> |---|---|
> | Next.js aparte | Páginas HTML servidas por FastAPI (Jinja2); JS solo donde haga falta (timeline) |
> | PostgreSQL | SQLite en `datos/faceless.db` |
> | Redis + Celery | Cola de tareas persistida en SQLite + worker en un hilo del mismo proceso (M2) |
> | SeaweedFS/S3 | Carpeta local `datos/` |
> | FFmpeg del sistema | `imageio-ffmpeg` (binario incluido vía pip) |
> | Docker Compose | `Iniciar.bat` (instala uv, que descarga Python y dependencias) |
>
> Las interfaces de proveedores y el diseño por etapas no cambian; si algún día se
> sube a un servidor, se pueden recuperar Postgres y una cola externa.
> Las secciones 5, 6, 12, 13 y 14 describen la pila v0.2 y se mantienen como referencia.
>
> Contexto: 2 usuarios (el dueño y un amigo), se ejecuta en un ordenador personal
> con Docker, y el presupuesto en APIs es mínimo: se priorizan las opciones gratuitas
> o locales y las de pago quedan como opcionales.
> Fuente: "Prompt maestro" del proyecto (instrucciones originales, secciones 1–47).

Este documento cubre los pasos 1–13 de la sección 47 del prompt maestro:
análisis, requisitos, riesgos, arquitectura, stack, base de datos, APIs, UX,
milestones y MVP.

---

## 1. Análisis y decisiones clave

El prompt describe un producto muy grande (≈16 motores). Tres decisiones lo
hacen viable:

1. **El pipeline es un grafo de etapas persistidas, no un script.** Cada etapa
   guarda su entrada, su salida y un hash de la entrada. Si cambias un párrafo
   del guion, solo se marcan como *obsoletas* las escenas que dependen de él,
   y solo esas se regeneran (secciones 9 y 25).
2. **Todo proveedor externo va detrás de una interfaz** (`VoiceProvider`,
   `ImageProvider`…). El núcleo nunca importa un SDK concreto (secciones 32 y 45).
3. **El vídeo se describe como datos antes de renderizarse.** El storyboard y
   el montaje producen un `Timeline` JSON (pistas, clips, tiempos). El editor de
   la interfaz edita ese JSON; el worker de render lo convierte en MP4 con FFmpeg.
   Así el montaje automático, el editor manual y el render comparten un único
   formato.

### Ajuste propuesto al MVP del prompt

La Fase 1 del prompt incluye exportación pero deja la generación visual para la
Fase 2, así que el primer vídeo exportado no tendría imágenes. Propongo meter en
el MVP **visuales de stock gratuitos** (Pexels/Pixabay) y dejar la generación con
IA (imagen y vídeo) para la Fase 2. Así el MVP produce un vídeo publicable
desde el primer día.

También propongo que el editor del MVP sea un **editor por escenas** (reordenar,
cambiar visual, ajustar duración, editar texto en pantalla) y no un timeline de
6 pistas. El timeline completo es la pieza de interfaz más cara del proyecto y
encaja mejor en la Fase 2, cuando el formato `Timeline` ya esté probado.

---

## 2. Requisitos funcionales (resumen)

| Área | Requisito | Fase |
|---|---|---|
| Proyectos | CRUD, estados (Idea → Publicado), progreso por etapa | 1 |
| Entrada | Tema, duración, idioma, tipo, nivel de automatización | 1 |
| Investigación | Búsqueda web multi-fuente, brief con afirmaciones ↔ fuentes | 1 |
| Estrategia | Ángulos, títulos y conceptos de miniatura para elegir | 1 |
| Guion | Estructura hook→CTA, tono/estilo, regenerar por párrafo | 1 |
| Storyboard | Guion → escenas con todos los campos de la sección 10 | 1 |
| Visual Bible | Consistencia de personajes, estilo y paleta por proyecto | 1 (datos) / 2 (uso en IA) |
| Visuales | Stock (F1), imagen IA (F2), vídeo IA (F2+) | 1–2 |
| Voz | Varios proveedores TTS, muestra previa, marcas temporales por palabra | 1 |
| Audio | Música de biblioteca con licencia, SFX, ducking | 1 (música) / 2 (SFX) |
| Montaje | Primer montaje automático → `Timeline` | 1 |
| Editor | Por escenas (F1), timeline multipista (F2) | 1–2 |
| Subtítulos | SRT + quemados, estilo Shorts palabra a palabra | 1 (SRT) / 2 (animados) |
| Miniaturas | 4 propuestas con concepto, prompt y composición | 2 |
| SEO | Título, descripción, capítulos, tags, comentario fijado | 2 |
| QC | 8 comprobaciones; bloquea la publicación si hay fallos | 2 |
| Aprobaciones | Autopilot / Aprobación / Manual | 1 (Manual y Aprobación) / 2 (Autopilot) |
| Publicación | Subida y programación vía YouTube Data API | 3 |
| Analytics | YouTube Analytics API, snapshots periódicos | 3 |
| Calendario | Planificación de contenido | 3 |
| Memoria de canal | Nicho, tono, voz, histórico, preferencias | 3 |
| Aprendizaje | Patrones de rendimiento sin afirmar causalidad | 4 |
| Multicanal | Varios canales con memoria y branding propios | 4 (el esquema lo soporta desde F1) |
| Reutilización | Largo → Shorts/clips | 4 |
| Costes | Estimación previa y presupuesto máximo por vídeo | 1 (registro) / 2 (límite) |

## 3. Requisitos técnicos

- Procesos largos en segundo plano; la interfaz nunca se bloquea y el progreso
  se ve en tiempo real (sección 37).
- Recuperación: un fallo en una etapa no pierde el proyecto; se reintenta solo
  esa etapa (sección 34).
- Reintentos con *backoff* y proveedor alternativo configurable.
- Claves API cifradas en reposo y nunca devueltas a la interfaz (sección 35).
- Separación por usuario y canal en todas las consultas.
- Registro de coste por llamada a proveedor.

---

## 4. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Política de YouTube de "contenido no auténtico"** (contenido masivo, repetitivo o de plantilla) | Desmonetización del canal entero | El modo Aprobación es el predeterminado en publicación; QC con comprobación de repetición entre vídeos del canal; memoria de canal para dar una línea editorial propia; la investigación y el fact-check aportan valor real |
| **Divulgación de contenido sintético** | Sanciones si se oculta cuando es obligatoria | Cuando las escenas usan visuales IA realistas, el SEO Engine marca el aviso y la publicación rellena el campo de divulgación de la API. No se ofrece ninguna función para ocultarlo |
| **Proyectos de la API de YouTube sin verificar** | Los vídeos subidos quedan forzados como privados | Pasar la auditoría de Google para el proyecto de API antes de la Fase 3; mientras tanto, se exporta y se sube a mano |
| Cuota de la API de YouTube (10.000 unidades/día; una subida ≈ 1.600) | ~6 subidas al día por proyecto de API | Suficiente para 1–2 vídeos/día; la cola de publicación respeta la cuota |
| Alucinaciones en guion e investigación | Desinformación, pérdida de confianza | Cada afirmación lleva una fuente; el QC bloquea las afirmaciones sin fuente |
| Derechos de los recursos | Reclamaciones de copyright | Cada asset guarda proveedor, licencia y URL de origen; el QC bloquea los que no tienen licencia clara |
| Coste del vídeo con IA | Facturas imprevistas | Estimación previa, presupuesto máximo por vídeo y stock por defecto |
| Tiempo de render | Cola lenta | Workers de render separados y escalables; previsualización a baja resolución |
| Consistencia visual con IA | Personajes que cambian entre escenas | Visual Bible inyectada en cada prompt; QC de continuidad |
| Alcance enorme | No terminar nunca | Fases estrictas; nada de la Fase 2 entra hasta que el MVP produzca vídeos |

---

## 5. Arquitectura

```
┌──────────────────────────┐        ┌──────────────────────────────────────┐
│ FRONTEND (Next.js)       │  REST  │ BACKEND API (FastAPI)                │
│ Dashboard · Wizard       │◄──────►│ Auth · Proyectos · Canales · Assets  │
│ Editor guion · Escenas   │  SSE   │ Orquestador de pipeline              │
│ Preview · Ajustes        │◄───────│ Estimador de costes                  │
└──────────────────────────┘progreso└───────────────┬──────────────────────┘
                                                    │ encola tareas
                                         ┌──────────▼──────────┐
                                         │ Redis (cola + pubsub)│
                                         └──────────┬──────────┘
                    ┌───────────────────┬───────────┼────────────┬──────────────┐
             ┌──────▼─────┐     ┌───────▼─────┐ ┌───▼────────┐ ┌─▼──────────┐ ┌─▼────────┐
             │ worker:llm │     │ worker:media│ │worker:render│ │worker:pub  │ │ scheduler│
             │ research   │     │ voz, visual │ │ FFmpeg      │ │ YouTube    │ │ analytics│
             │ guion, SEO │     │ música, SFX │ │ subtítulos  │ │ upload     │ │ calendario│
             └──────┬─────┘     └──────┬──────┘ └─────┬──────┘ └─────┬──────┘ └────┬─────┘
                    │                  │              │              │             │
            ┌───────▼──────────────────▼──────────────▼──────────────▼─────────────▼──┐
            │ PROVIDERS (interfaces)  AI · Search · Image · Video · Voice · Music ·     │
            │                         Stock · Storage · YouTube                         │
            └───────┬───────────────────────────────────────────────────────────────────┘
                    │
     ┌──────────────▼─────────────┐      ┌───────────────────────────────┐
     │ PostgreSQL                 │      │ Object storage (S3 / R2 /     │
     │ estado, escenas, costes…   │      │ SeaweedFS): vídeo, audio,     │
     └────────────────────────────┘      │ imágenes, renders             │
                                         └───────────────────────────────┘
```

### Orquestador de pipeline

- Cada proyecto tiene una fila por etapa en `project_stages`
  (`pending | running | waiting_approval | done | failed | stale`).
- El orquestador lee el grafo de dependencias, lanza las etapas cuyas
  dependencias están `done` y se detiene en `waiting_approval` según el modo
  (Manual / Aprobación / Autopilot).
- Cada tarea es **idempotente**: si un worker muere, la tarea se reintenta y
  reutiliza lo ya generado (por ejemplo, las escenas con visual ya descargado).
- Al editar una salida, se recalcula el hash y se marcan como `stale` las etapas
  y escenas afectadas.

```
research → strategy → script → storyboard ─┬─→ visuals ─┐
                                           ├─→ voice ───┼─→ assembly → render → qc → publish
                                           └─→ music ───┘          ↘ thumbnail, seo ↗
```

---

## 6. Stack tecnológico

| Capa | Propuesta | Alternativa | Por qué |
|---|---|---|---|
| Frontend | **Next.js + TypeScript + Tailwind + shadcn/ui** | SvelteKit | Ecosistema más grande; buenos componentes para dashboards |
| Backend | **Python 3.12 + FastAPI + SQLAlchemy + Alembic** | Node/NestJS | El ecosistema de audio, vídeo e IA (FFmpeg, Whisper, pydub) es mejor en Python |
| Cola | **Celery + Redis** | Temporal | Celery es suficiente con el estado guardado en Postgres; Temporal es más robusto pero añade mucha infraestructura |
| Base de datos | **PostgreSQL 16** | — | JSONB para salidas flexibles de etapas |
| Storage | **S3-compatible** (SeaweedFS en local) | Cloudflare R2 si algún día se sube a un servidor | MinIO dejó de publicar imágenes Docker; SeaweedFS ofrece la misma API S3 |
| Render | **FFmpeg** a partir del `Timeline` JSON | Remotion | FFmpeg es gratuito y sin límites de licencia; Remotion es más cómodo para animaciones, pero exige licencia de pago para empresas |
| Tiempo real | **Server-Sent Events** | WebSockets | El progreso solo va en una dirección |
| Auth | **Sesiones con cookie httpOnly + Argon2, registro cerrado** (solo 2 cuentas, creadas por comando) | Clerk/Auth0 | Sin dependencias externas; no hace falta registro público |
| Secretos | **Cifrado con Fernet (AES) y clave maestra en variable de entorno** | Vault / KMS | Simple y suficiente para una persona o un equipo pequeño |
| Despliegue | **Docker Compose en el ordenador del usuario** | VPS más adelante | Un solo comando y coste cero |
| Tests | **pytest, Vitest, Playwright** | — | Unitarios, integración y E2E |

### Proveedores iniciales (todos intercambiables)

| Interfaz | MVP | Alternativas |
|---|---|---|
| `AIProvider` | **Gemini API (nivel gratuito con límites)** | Claude o OpenAI (API de pago por uso) |
| `SearchProvider` | Tavily (1.000 búsquedas/mes gratis) | Brave Search API, Exa |
| `StockProvider` | Pexels + Pixabay (gratis, con licencia de uso) | Storyblocks |
| `ImageProvider` | — (Fase 2) | fal.ai / Replicate (Flux), OpenAI Images |
| `VideoProvider` | — (Fase 2+) | Runway, Kling, Veo |
| `VoiceProvider` | **Piper (local y gratis)** | Gemini TTS, ElevenLabs (de pago, mejor calidad), OpenAI TTS |
| `MusicProvider` | Biblioteca local con licencia | Proveedores con API y licencia comercial |
| `StorageProvider` | SeaweedFS (local) | R2, AWS S3 |
| `YouTubeProvider` | — (Fase 3) | YouTube Data API v3 + Analytics API |

Subtítulos: marcas de tiempo del TTS cuando las haya; si no, alineación con
`faster-whisper` en local (sin coste).

---

## 7. Esquema de base de datos (núcleo)

```
users(id, email, password_hash, created_at)
channels(id, user_id, name, niche, language, branding JSONB, default_voice JSONB)
channel_memory(id, channel_id, kind, content JSONB, updated_at)       -- F3
provider_credentials(id, user_id, provider, encrypted_key, last4, created_at)

projects(id, channel_id, title, topic, type, language, target_duration_s,
         automation_mode, status, budget_max_cents, scheduled_at, created_at)
project_stages(id, project_id, stage, status, progress, input_hash,
               output JSONB, error JSONB, attempts, started_at, finished_at)

sources(id, project_id, url, title, publisher, retrieved_at, reliability)
claims(id, project_id, text, status[verified|unverified|disputed], source_ids[])

script_versions(id, project_id, version, structure JSONB, created_at)
script_segments(id, script_version_id, position, section, text, hash)

visual_bible(id, project_id, characters JSONB, locations JSONB, style JSONB)
scenes(id, project_id, position, segment_ids[], duration_ms, narration,
       visual_desc, motion, transition, on_screen_text, music_cue, sfx JSONB,
       visual_prompt, source_ids[], status, hash)

assets(id, project_id, scene_id, kind[image|video|audio|music|sfx|thumbnail|render],
       provider, storage_key, license, origin_url, meta JSONB, created_at)
timelines(id, project_id, version, spec JSONB, created_at)
thumbnails(id, project_id, concept JSONB, asset_id, selected)          -- F2
seo_metadata(id, project_id, title, description, chapters JSONB,
             tags[], pinned_comment, category, synthetic_disclosure)    -- F2
qc_reports(id, project_id, passed, created_at)                          -- F2
qc_issues(id, report_id, check, severity, scene_id, problem, proposal)  -- F2

publications(id, project_id, youtube_video_id, privacy, published_at)  -- F3
metric_snapshots(id, publication_id, captured_at, data JSONB)          -- F3
calendar_entries(id, channel_id, project_id, date, priority, status)   -- F3

cost_entries(id, project_id, stage, provider, units, cost_cents, created_at)
job_logs(id, project_id, stage, level, message, data JSONB, created_at)
```

---

## 8. APIs

### API interna (backend ↔ frontend), resumen

```
POST   /auth/register | /auth/login | /auth/logout
GET    /channels                      POST /channels
GET    /projects?channel_id=          POST /projects
GET    /projects/{id}                 DELETE /projects/{id}   (con confirmación)
GET    /projects/{id}/events          (SSE: progreso en tiempo real)
POST   /projects/{id}/estimate        → coste y tiempo estimados
POST   /projects/{id}/run             (lanza el pipeline según el modo)
POST   /projects/{id}/stages/{stage}/run | /approve | /regenerate
GET    /projects/{id}/research        (brief + fuentes + claims)
GET    /projects/{id}/script          PATCH /projects/{id}/script/segments/{seg}
POST   /projects/{id}/script/segments/{seg}/rewrite  {action: expand|summarize|tone}
GET    /projects/{id}/scenes          PATCH /scenes/{id}   POST /scenes/{id}/regenerate
GET    /projects/{id}/timeline        PUT /projects/{id}/timeline
POST   /projects/{id}/render?quality=preview|final
GET    /voices?provider=              POST /voices/sample
PUT    /settings/providers/{provider} (guarda la clave; solo devuelve los 4 últimos caracteres)
```

### APIs externas necesarias

| API | Fase | Necesita |
|---|---|---|
| Gemini API | 1 | Clave gratuita de Google AI Studio |
| Tavily (o Brave Search) | 1 | Clave gratuita |
| Pexels, Pixabay | 1 | Claves gratuitas |
| Anthropic / OpenAI / ElevenLabs | Opcional | Clave API de pago por uso |
| fal.ai / Replicate | 2 | Clave API |
| YouTube Data API v3 + Analytics API | 3 | Proyecto en Google Cloud, OAuth y **auditoría** para subir vídeos públicos |

---

## 9. Interfaces entre módulos

```python
class VoiceProvider(Protocol):
    name: str

    def list_voices(self, language: str) -> list[Voice]: ...
    def estimate_cost(self, text: str) -> Money: ...
    def synthesize(self, text: str, voice: VoiceSettings) -> SynthesisResult:
        """Devuelve el audio y, si el proveedor lo permite, marcas de tiempo por palabra."""


class StockProvider(Protocol):
    name: str

    def search(
        self, query: str, kind: Literal["image", "video"], orientation: Orientation, limit: int
    ) -> list[StockResult]: ...
    def download(self, result: StockResult) -> DownloadedAsset: ...  # incluye la licencia
```

Cada etapa del pipeline sigue el mismo contrato:

```python
class Stage(Protocol):
    name: StageName
    depends_on: list[StageName]

    def input_hash(self, ctx: ProjectContext) -> str: ...
    def estimate(self, ctx: ProjectContext) -> Estimate: ...
    def run(self, ctx: ProjectContext, progress: ProgressReporter) -> StageOutput: ...
```

La resolución de proveedores (`ProviderRegistry`) lee la configuración del
usuario y aplica la cadena de alternativas (por ejemplo, ElevenLabs → OpenAI TTS)
cuando un proveedor falla después de agotar los reintentos.

---

## 10. Flujo UX (MVP)

```
Login → Dashboard (tarjetas de proyecto con estado y progreso)
  → [+ Nuevo vídeo] Wizard: tema · duración · idioma · tipo · modo
  → Coste y tiempo estimados → [Empezar]
  → Vista de proyecto con barra de etapas (Research ✓ · Script 40% · …)
      ├─ Research: brief, afirmaciones con su fuente
      ├─ Estrategia: 3 ángulos + títulos → elegir uno     [aprobación]
      ├─ Guion: editor por párrafos (regenerar/expandir/tono) [aprobación]
      ├─ Escenas: lista con visual, duración y texto; cambiar visual
      ├─ Voz: elegir voz → muestra de 15 s → generar
      └─ Preview: reproductor a baja resolución → [Render final] → Descargar MP4 + SRT
```

---

## 11. Milestones

| # | Milestone | Resultado verificable |
|---|---|---|
| M0 ✅ | Esqueleto | `docker compose up` levanta frontend, API, worker, Postgres, Redis y SeaweedFS; CI con tests |
| M1 ✅ | Auth + canales + proyectos | Login, crear canal, crear proyecto, dashboard |
| M2 ✅ | Orquestador | Etapas con estados, SSE, reintentos, aprobación; etapa de prueba de punta a punta |
| M3 ✅ | Research + estrategia | Brief con fuentes reales para un tema |
| M4 ✅ | Guion + editor | Guion editable por párrafos; marca escenas obsoletas |
| M5 (escenas ✅, stock pendiente) | Storyboard + stock | Escenas con visual de stock y licencia guardada |
| M6 (voz ✅, subtítulos pendientes) | Voz + subtítulos | Narración por escena + SRT sincronizado |
| M7 | Montaje + render | **Primer MP4 completo** con música, voz, visuales y subtítulos |
| M8 | Costes + editor por escenas | Estimación previa, presupuesto máximo, edición y re-render |
| — | **Fin del MVP** | De una idea a un MP4 descargable |

Fase 2: imágenes y vídeo con IA, Visual Bible aplicada, miniaturas, SEO, QC
completo, Autopilot, timeline multipista, subtítulos animados, SFX.
Fase 3: YouTube API (subida y programación), Analytics, calendario, memoria de canal.
Fase 4: aprendizaje, multicanal avanzado, reutilización a Shorts.

---

## 12. Estructura de carpetas

```
automatizacion-yt/
├─ apps/
│  ├─ web/                    # Next.js
│  │  └─ src/{app,components,lib}
│  └─ api/                    # FastAPI + workers
│     ├─ app/
│     │  ├─ api/              # routers REST + SSE
│     │  ├─ core/             # config, seguridad, cifrado
│     │  ├─ db/               # modelos, sesiones, migraciones (alembic)
│     │  ├─ pipeline/         # orquestador + una carpeta por etapa
│     │  │  ├─ research/  strategy/  script/  storyboard/
│     │  │  ├─ visuals/   voice/     audio/   assembly/  render/
│     │  │  └─ qc/        seo/       thumbnail/ publish/
│     │  ├─ providers/        # interfaces + implementaciones
│     │  │  ├─ ai/ search/ stock/ image/ video/ voice/ music/ storage/ youtube/
│     │  ├─ timeline/         # esquema Timeline + compilador a FFmpeg
│     │  └─ workers/          # tareas Celery
│     └─ tests/
├─ docs/                      # este documento + un README por módulo
├─ docker-compose.yml         # entorno local completo
└─ .env.example
```

## 13. Variables de entorno

```
APP_ENV=development
SECRET_KEY=                  # sesiones
ENCRYPTION_KEY=              # Fernet: cifra las claves API de los usuarios
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=redis://redis:6379/0
S3_ENDPOINT=  S3_BUCKET=  S3_ACCESS_KEY=  S3_SECRET_KEY=
WEB_ORIGIN=http://localhost:3000
# Opcionales a nivel de servidor (los usuarios también pueden guardar las suyas cifradas)
GEMINI_API_KEY=  TAVILY_API_KEY=  PEXELS_API_KEY=  PIXABAY_API_KEY=
# De pago, opcionales: ANTHROPIC_API_KEY=  OPENAI_API_KEY=  ELEVENLABS_API_KEY=
```

## 14. Despliegue

- **Local (modo principal):** `docker compose up --build` (todo incluido, SeaweedFS como storage).
- **Si algún día se quiere en un servidor:** un VPS (4 vCPU / 8 GB basta para 1–2 vídeos al día) con
  Docker Compose, Caddy para HTTPS, Postgres gestionado o en contenedor con
  copias de seguridad diarias, y R2 como storage. El render es el cuello de
  botella: se escala añadiendo réplicas de `worker:render`.
- CI en GitHub Actions: lint, tipos y tests en cada push.

---

## 15. Suscripciones frente a APIs

Las suscripciones de chat (Claude Pro, ChatGPT Plus, Gemini) **no incluyen acceso
por API**: las APIs se pagan aparte, por uso. Por eso el MVP se apoya en:

- **Gemini API**, con nivel gratuito (límites por minuto y por día; suficiente para
  1–2 vídeos al día). Los datos del nivel gratuito pueden usarse para mejorar los
  productos de Google, así que no se envía nada privado.
- **Modelos locales** donde sea viable: Piper para la voz y faster-whisper para los
  subtítulos.
- **Stock gratuito** (Pexels/Pixabay) para los visuales.

Las suscripciones siguen siendo útiles para trabajo manual (pulir un guion,
generar una miniatura en el chat de ChatGPT o Gemini, etc.).

---

## 16. Notas de implementación (M2–M3)

- **Cola de tareas** (`app/jobs.py`): tabla `jobs` en SQLite y un único hilo trabajador.
  Reintenta los errores temporales (límite de uso, servicio caído) hasta 3 veces con
  espera; al arrancar, las tareas que quedaron a medias vuelven a la cola.
- **Investigación** (`app/pipeline/research.py`): en lugar de Tavily se usa la
  *búsqueda de Google integrada en Gemini* (grounding), así basta con una sola clave
  gratuita. Paso 1: búsqueda con fuentes reales y marcas [n] insertadas a partir de los
  metadatos de Gemini. Paso 2: se estructura en JSON. Los números de fuente que no
  existen se descartan y el dato pasa a «por verificar»: nunca se inventan fuentes.
- **Modelo**: se elige automáticamente el Gemini Flash estable más reciente que la
  clave tenga disponible (`pick_flash_model`); si no se puede listar, `gemini-2.5-flash`.
- **Claves API**: se guardan cifradas (Fernet) desde la página Configuración; la clave
  de cifrado vive en `datos/encryption.key`. La interfaz solo muestra los 4 últimos
  caracteres.

- **Plan B de investigación (v0.3.2)**: si la búsqueda de Google integrada en Gemini no
  tiene cuota gratuita en la cuenta del usuario, la investigación usa Wikipedia
  (`app/providers/search.py`, API pública de MediaWiki, sin clave): Gemini propone
  búsquedas, se descargan los artículos y Gemini redacta el informe citando solo esos
  documentos. Los errores temporales no activan el plan B (se reintenta con Google).
- **Diagnóstico**: Configuración → «Probar conexión» prueba por separado la clave, la
  generación de texto y la búsqueda de Google en los dos primeros modelos, y Wikipedia.
- **Cuotas**: los errores 429 se clasifican con los `QuotaFailure.violations` de Google
  (por minuto → reintento; por día o límite 0 → sin reintento, se prueba otro modelo).

## 17. Notas de implementación (M3 estrategia y M4 guion, v0.4)

- **Estrategia** (`app/pipeline/strategy.py`): 3 enfoques con audiencia, promesa, gancho,
  3 títulos (estilo + razón, sin métricas inventadas) y concepto de miniatura. El usuario
  elige enfoque y título (`selected`).
- **Guion** (`app/pipeline/script.py`): secciones hook → promise → intro → development →
  climax → conclusion → cta; extensión según la duración (~150 palabras/min); tono,
  dramatismo y nivel técnico configurables. Cada párrafo tiene un `id` estable (servirá
  para saber qué escenas del storyboard quedan afectadas) y sus números de fuente.
- **Editor**: por párrafo, edición manual, borrar, o con IA: reescribir, alargar, resumir
  y cambiar tono (síncrono, usando los párrafos vecinos como contexto).
- **Modos**: manual (nada encadenado); asistido (tras investigar, se proponen enfoques y
  se espera la elección); automático (elige el primer enfoque y escribe el guion).
- **Migración ligera**: `init_db` añade a las tablas existentes las columnas nuevas
  opcionales (p. ej. `jobs.params`) para no perder datos al actualizar.
- **Páginas**: el proyecto tiene pestañas Resumen / Investigación / Estrategia / Guion.

## 18. Notas de implementación (escenas y voz, v0.5)

- **Escenas** (`app/pipeline/storyboard.py`): una escena por párrafo del guion (por su
  `id`), con biblia visual del proyecto, tipo de visual, búsqueda de stock (en inglés),
  prompt de imagen, movimiento, transición, texto en pantalla, SFX y ambiente musical.
  Cada escena guarda el texto del párrafo con el que se creó; `stale_scenes` detecta las
  escenas cuyo texto cambió y los párrafos nuevos sin escena.
- **Voz** (`app/providers/voice.py`, `app/pipeline/voice.py`): Piper (local, gratis).
  Las voces se descargan una vez a `datos/voces/` (descarga atómica con `.part`).
  Grabación por párrafo con clave = hash(voz, velocidad, texto): al regrabar solo se
  sintetizan los párrafos cambiados. Se une todo en `voz/narracion.wav` con pausas de
  0,35 s. Muestra de voz síncrona desde la página Voz.
- **Archivos**: `datos/proyectos/<id>/`, servidos con sesión y protección de rutas.
- **Pendiente**: Piper no se ha probado con una voz real en el entorno de desarrollo (sin
  acceso a HuggingFace); las pruebas usan una voz simulada.

- **Extensión del guion (v0.5.1)**: los modelos rápidos escribían guiones muy cortos
  (10–15 min salía en ~5 min). Ahora el guion se escribe en dos pasos: un esquema con
  objetivo de palabras por sección (`plan_sections`: gancho 4 %, promesa 4 %, intro 8 %,
  desarrollo 62 % repartido en 2–6 secciones, clímax 12 %, conclusión 7 %, llamada 3 %) y
  luego cada sección por separado, con la anterior como contexto. Si una sección queda
  por debajo del 75 % de su objetivo, se pide una versión más larga. Los errores
  temporales se reintentan dentro de la misma tarea (20 s, 40 s) para no perder lo escrito.
