"""IMÁGENES CON GOOGLE FLOW (gratis): el método con el que mejor quedan los vídeos.

Google no deja que un programa cree imágenes en Flow él solo (lo bloquea como «actividad
inusual»), así que el reparto de trabajo es:

1. El programa prepara los mensajes para el ASISTENTE de Flow (9 escenas por mensaje),
   con el estilo stickman y el mismo protagonista en todas.
2. El creador pega cada mensaje en el asistente de Flow (Nano Banana, 0 puntos).
3. En Flow abre la primera imagen y pulsa el marcador «Recoger imágenes de Flow»: recorre
   el visor con las flechas y copia los enlaces de descarga.
4. Pega esos enlaces en el programa: las descarga, Gemini mira cada una y la coloca en su
   escena. Si Gemini no puede, se colocan por orden de creación.
"""

import io
import json
import re
from urllib.parse import urlparse

import httpx

from app.providers.ai import ProviderError

PER_MESSAGE = 24  # el asistente de Flow no acepta más de 24 imágenes por petición
FLOW_HOST = "flow-content.google"
MAX_IMAGES = 120
MAX_BYTES = 20 * 1024 * 1024

# Estilo único de todos los vídeos (el que eligió el creador: stickman 2D).
STICKMAN_STYLE = (
    "2D stickman animation style, simple white stick figures with round heads and thick black "
    "outlines, simple expressive eyes, flat colors, clean vector illustration, simple shapes, "
    "dark green and night tones with yellow and red accents, cinematic composition"
)
NO_TEXT = "no text, no letters, no numbers on signs, no logos, no watermark"


def protagonist_hint(visual_bible: dict) -> str:
    """El protagonista, igual en todas las imágenes (si el guion tiene uno)."""
    people = [c for c in (visual_bible.get("characters") or []) if c.strip()]
    return people[0].strip() if people else ""


# «football» en inglés: Nano Banana dibuja a menudo un balón de fútbol americano.
SOCCER_WORDS = (
    (re.compile(r"\bfootballers\b", re.I), "soccer players"),
    (re.compile(r"\bfootballer\b", re.I), "soccer player"),
    (
        re.compile(
            r"\bfootball(?=\s+(?:stadium|pitch|field|match|game|team|club|shirt|kit|boots"
            r"|player|fans|academy|school|career|legend|star))",
            re.I,
        ),
        "soccer",
    ),
    (
        re.compile(r"\b(play(?:s|ing|ed)?|watch(?:es|ing|ed)?|love[sd]?) football\b", re.I),
        r"\1 soccer",
    ),
    (re.compile(r"\b(?:a |the )?(?:soccer )?football\b(?!\s+ball)", re.I), "a soccer ball"),
)
SOCCER_RULE = (
    "BALLS: every ball is a round black-and-white soccer ball (association football). "
    "NEVER draw an American football or a rugby ball."
)
SOCCER_HINT = re.compile(r"\b(?:soccer|football\w*|fútbol|futbol|balón|goal|stadium)\b", re.I)


def soccer_words(text: str) -> str:
    for pattern, word in SOCCER_WORDS:
        text = pattern.sub(word, text)
    return text


def scene_prompt(scene: dict, visual_bible: dict) -> str:
    base = (scene.get("image_prompt") or scene.get("visual") or "").strip().rstrip(".")
    return soccer_words(base)


def single_message(board: dict, portrait: bool = False) -> str:
    """Todas las escenas en un solo mensaje (si el asistente se para, se le pide seguir)."""
    parts = messages(board, portrait, per_message=max(len(board.get("scenes", [])), 1))
    if not parts:
        return ""
    return parts[0]["text"].replace(
        "Do not ask me anything, just create them all.",
        "Do not ask me anything and do not stop until ALL of them are created; if you must "
        "pause, continue automatically with the next number.",
    )


def messages(board: dict, portrait: bool = False, per_message: int = PER_MESSAGE) -> list[dict]:
    """Los mensajes para pegar en el asistente de Flow: [{"first", "last", "text"}]."""
    scenes = board.get("scenes", [])
    bible = board.get("visual_bible") or {}
    hero = protagonist_hint(bible)
    shape = "9:16" if portrait else "16:9"
    parts = []
    for start in range(0, len(scenes), per_message):
        chunk = scenes[start : start + per_message]
        first, last = chunk[0]["number"], chunk[-1]["number"]
        lines = [
            f"Create {len(chunk)} SEPARATE images, one for each numbered description below, in "
            f"this exact order ({first} to {last}). Use Nano Banana, {shape}, one image each. "
            "Do not ask me anything, just create them all.",
            f"SAME STYLE FOR ALL: {STICKMAN_STYLE}, {NO_TEXT}.",
        ]
        if hero:
            lines.append(
                f"MAIN CHARACTER (identical in every image where he appears, a recognizable "
                f"caricature): {soccer_words(hero)}."
            )
        if any(SOCCER_HINT.search(s.get("image_prompt") or s.get("visual") or "") for s in chunk):
            lines.append(SOCCER_RULE)
        lines.append("")
        lines += [f"{s['number']}. {scene_prompt(s, bible)}" for s in chunk]
        parts.append({"first": first, "last": last, "text": "\n".join(lines)})
    return parts


# Marcador para el navegador del creador: se pulsa con el visor de Flow abierto en la
# imagen más nueva. Recorre las imágenes con la flecha → (solo mira, no crea nada) y copia
# al portapapeles los enlaces de descarga con su título.
BOOKMARKLET = (
    "javascript:(async()=>{const s=m=>new Promise(r=>setTimeout(r,m));"
    "const c=()=>{const a=(x)=>{const r=x.getBoundingClientRect();return r.width*r.height};"
    "const i=[...document.querySelectorAll('img')].filter(x=>x.src.includes("
    "'flow-content.google/image')).sort((x,y)=>a(y)-a(x))[0];"
    "const h=document.querySelector('h1,h2,[class*=title]');"
    "return{t:h?h.innerText:'',s:i?i.src:''}};let a=c();if(!a.s){alert('Abre primero la imagen "
    "más nueva en Flow (haz clic en ella) y vuelve a pulsar el marcador.');return}"
    "const o=[a];for(let n=0;n<__MAX__;n++){const p=a.s;['keydown','keyup'].forEach(t=>"
    "document.dispatchEvent(new KeyboardEvent(t,{key:'ArrowRight',code:'ArrowRight',"
    "keyCode:39,bubbles:true})));for(let w=0;w<15;w++){await s(200);a=c();if(a.s&&a.s!==p)"
    "break}if(a.s===p)break;o.push(a)}const j=JSON.stringify(o.slice(0,__COUNT__));"
    "try{await navigator.clipboard.writeText(j);alert('Copiados '+Math.min(o.length,__COUNT__)"
    "+' enlaces. Vuelve a Faceless Studio y pégalos.')}catch(e){prompt('Copia este texto:',j)}})()"
)


def project_token(project_id: int) -> str:
    """Clave del botón «Enviar a Faceless Studio» de un proyecto (no sirve para nada más)."""
    import hashlib
    import hmac

    from app.config import SECRET_KEY

    return hmac.new(SECRET_KEY.encode(), f"flow:{project_id}".encode(), hashlib.sha256).hexdigest()[
        :32
    ]


# Botón directo: dentro del proyecto de Flow, recorre la cuadrícula (de la más nueva a la más
# vieja), descarga cada imagen con la sesión de Flow del propio navegador y la envía a Faceless
# Studio, que la coloca en su escena. Solo lee imágenes ya creadas: no crea nada en Flow.
DIRECT = (
    "javascript:(async()=>{const API='__API__',N=__N__,s=m=>new Promise(r=>setTimeout(r,m));"
    "const b=document.createElement('div');b.style.cssText='position:fixed;top:12px;left:50%;"
    "transform:translateX(-50%);z-index:999999;background:#111;color:#c6ff3a;padding:12px 18px;"
    "border-radius:10px;font:16px sans-serif;box-shadow:0 4px 20px #000';document.body.append(b);"
    "const say=t=>b.textContent=t;say('Faceless Studio: buscando imágenes…');"
    "const g=[...document.querySelectorAll('*')].filter(e=>e.scrollHeight>e.clientHeight+50&&"
    "/(auto|scroll)/.test(getComputedStyle(e).overflowY)).sort((x,y)=>y.scrollHeight-x.scrollHeight)[0];"
    "if(!g||!document.querySelector('flow-grid-tile-container')){say('Abre primero tu proyecto de "
    "Flow (donde se ven las imágenes) y vuelve a pulsar el botón.');setTimeout(()=>b.remove(),6000);"  # noqa: E501
    "return}const u=[];g.scrollTop=0;await s(600);for(let y=0;y<g.scrollHeight+800&&u.length<N;y+=300)"  # noqa: E501
    "{g.scrollTop=y;await s(250);document.querySelectorAll('flow-grid-tile-container img').forEach(i=>"  # noqa: E501
    "{const k=i.src;if(k&&!u.includes(k)&&u.length<N)u.push(k)})}g.scrollTop=0;const f=new FormData();"  # noqa: E501
    "for(let k=0;k<u.length;k++){say('Faceless Studio: descargando '+(k+1)+' de '+u.length+'…');"
    "try{const r=await fetch(u[k]);if(r.ok)f.append('images',await r.blob(),'flow-'+k+'.img')}"
    "catch(e){}}say('Faceless Studio: colocando las imágenes en sus escenas (1-2 minutos)…');"
    "try{const r=await fetch(API,{method:'POST',body:f});const j=await r.json();"
    "say(j.error?('Error: '+j.error):('¡Listo! '+j.placed+' imágenes colocadas.'+(j.missing.length?"
    "' Faltan las escenas: '+j.missing.join(', '):' Todas las escenas tienen imagen.')))}"
    "catch(e){say('No se pudo conectar con Faceless Studio. ¿Está abierto?')}"
    "setTimeout(()=>b.remove(),15000)})()"
)


def direct_bookmarklet(base_url: str, project_id: int, count: int) -> str:
    """El botón para arrastrar a la barra de marcadores (uno por proyecto)."""
    api = (
        f"{base_url.rstrip('/')}/proyectos/{project_id}/visuales/flow-directo"
        f"?k={project_token(project_id)}"
    )
    n = max(1, min(count + 20, MAX_IMAGES))
    return DIRECT.replace("__API__", api).replace("__N__", str(n))


def bookmarklet(count: int) -> str:
    """El marcador para `count` imágenes (más unas pocas de margen por si hay repetidas)."""
    count = max(1, min(count, MAX_IMAGES))
    return BOOKMARKLET.replace("__MAX__", str(min(count + 15, MAX_IMAGES))).replace(
        "__COUNT__", str(min(count + 15, MAX_IMAGES))
    )


def parse_links(raw: str) -> list[dict]:
    """Del texto pegado a [{"title", "url"}]. Acepta el JSON del marcador o enlaces sueltos.
    Solo se aceptan enlaces https de Flow (no se descarga nada de otros sitios)."""
    raw = (raw or "").strip()
    items: list[dict] = []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    items.append(
                        {"title": str(entry.get("t", ""))[:200], "url": entry.get("s", "")}
                    )
                elif isinstance(entry, str):
                    items.append({"title": "", "url": entry})
    except ValueError:
        items = [{"title": "", "url": u} for u in re.findall(r"https://\S+", raw)]
    seen, clean = set(), []
    for item in items:
        url = str(item["url"]).strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != FLOW_HOST or url in seen:
            continue
        seen.add(url)
        clean.append({"title": item["title"], "url": url})
    return clean[:MAX_IMAGES]


def download(url: str, client: httpx.Client) -> bytes:
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        raise ProviderError(
            "No se pudo descargar una imagen de Flow.", transient=True, detail=str(exc)[:200]
        ) from exc
    if response.status_code >= 400:
        raise ProviderError(
            "Flow no dejó descargar una imagen (los enlaces caducan a las pocas horas: vuelve "
            "a pulsar el marcador en Flow).",
            detail=f"{response.status_code}",
        )
    if len(response.content) > MAX_BYTES:
        raise ProviderError("Una imagen de Flow es demasiado grande.")
    return response.content


def thumbnail(data: bytes, size: int = 384) -> bytes:
    from PIL import Image

    picture = Image.open(io.BytesIO(data)).convert("RGB")
    picture.thumbnail((size, size))
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=80)
    return out.getvalue()


MATCH_BATCH = 8  # con muchas imágenes de golpe, Gemini solo empareja unas pocas


def match_with_ai(ai, thumbs: list[bytes], scenes: list[dict]) -> dict[int, int]:
    """Gemini mira las imágenes (de 8 en 8) y dice a qué escena va cada una: {imagen: escena}.
    Cada escena se usa una sola vez."""
    result: dict[int, int] = {}
    for start in range(0, len(thumbs), MATCH_BATCH):
        free = [s for s in scenes if s["number"] not in result.values()]
        if not free:
            break
        part = _match_batch(ai, thumbs[start : start + MATCH_BATCH], free)
        result.update({start + index: scene for index, scene in part.items()})
    return result


def _match_batch(ai, thumbs: list[bytes], scenes: list[dict]) -> dict[int, int]:
    from google.genai import types

    listing = "\n".join(
        f"{s['number']}. {s.get('image_prompt') or s.get('visual', '')}" for s in scenes
    )
    contents: list = [
        "You will see several images, numbered in order (IMAGE 1, IMAGE 2...). Each one was "
        "generated from ONE of these scene descriptions:\n" + listing + "\n\nFor every image, "
        'say which scene number it shows. Answer only JSON: {"pairs": [{"image": 1, '
        '"scene": 4}, ...]}. Use each scene at most once; if an image matches nothing, skip it.'
    ]
    for n, thumb in enumerate(thumbs, 1):
        contents += [f"IMAGE {n}", types.Part.from_bytes(data=thumb, mime_type="image/jpeg")]
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
    response = ai._generate(contents, config)
    data = json.loads(response.text or "{}")
    valid = {s["number"] for s in scenes}
    result, used = {}, set()
    for pair in data.get("pairs", []):
        try:
            image, scene = int(pair["image"]), int(pair["scene"])
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= image <= len(thumbs) and scene in valid and scene not in used:
            result[image - 1] = scene
            used.add(scene)
    return result


def by_order(count: int, scenes: list[dict]) -> dict[int, int]:
    """Sin Gemini: el visor de Flow va de la más nueva a la más vieja, así que se dan la
    vuelta y se colocan en orden de escena."""
    numbers = [s["number"] for s in scenes]
    order = list(range(count))[::-1]
    return {index: numbers[pos] for pos, index in enumerate(order) if pos < len(numbers)}
