# Faceless Studio

Plataforma para producir vídeos *faceless* de YouTube: de una idea a un vídeo listo
para publicar (investigación → guion → escenas → voz → montaje → exportación).

- Diseño y plan completo: [`docs/00-diseno-plataforma.md`](docs/00-diseno-plataforma.md)
- Estado: **M0 — base del proyecto** (servicios levantados y comprobación de salud).

## Requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows, macOS o Linux)
- [Git](https://git-scm.com/downloads)
- 8 GB de RAM como mínimo (16 GB recomendado para el render)

## Arrancar en tu ordenador

```bash
git clone https://github.com/nexolunch2026/automatizacion-yt.git
cd automatizacion-yt
git checkout claude/hola-5p4ttp     # hasta que se fusione en la rama principal
docker compose up --build
```

La primera vez tarda unos minutos en descargar e instalar todo. Después:

| Qué | Dirección |
|---|---|
| Aplicación web | http://localhost:3000 |
| Documentación de la API | http://localhost:8000/docs |
| Estado de los servicios | http://localhost:8000/health |

En la web deberías ver los cuatro servicios en verde: base de datos, cola,
almacenamiento y worker.

Para pararlo: `Ctrl + C`, o `docker compose down`. Los datos se conservan
entre arranques. Si quieres borrarlo todo: `docker compose down -v`.

## Configuración

Copia `.env.example` como `.env`. En este milestone no hace falta rellenar nada;
las claves gratuitas (Gemini, Tavily, Pexels, Pixabay) se usarán a partir de M3.

## Estructura

```
apps/api/   Backend (FastAPI), workers (Celery) y pipeline
apps/web/   Interfaz (Next.js)
docs/       Diseño y documentación de módulos
```

## Desarrollo sin Docker (opcional)

```bash
cd apps/api && pip install -e ".[dev]" && pytest
cd apps/web && npm install && npm run dev
```
