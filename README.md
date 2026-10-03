# Faceless Studio

Programa para crear vídeos de YouTube sin salir en cámara.
Por ahora tiene: **cuentas para 2 personas, canales, proyectos de vídeo, investigación
automática con fuentes, propuestas de enfoques y títulos, guion editable, escenas y
narración con voz (Piper o ElevenLabs), imágenes generadas con IA o de Pixabay, y
montaje del vídeo MP4 con subtítulos, textos de publicación (título, descripción con
capítulos, etiquetas), 3 miniaturas con el estilo del canal para elegir, Shorts verticales con los mejores momentos y gráficos animados con las cifras del guion**.
La creación automática de los vídeos se irá añadiendo poco a poco.

---

## Cómo instalarlo en Windows (paso a paso)

### Paso 1 — Instalar (un solo paso, y deja todo ordenado)
1. Si el programa está abierto, cierra la **ventana negra**.
2. Pulsa las teclas **Windows + R**. Se abre una cajita llamada «Ejecutar».
3. Copia esto, pégalo en la cajita y pulsa **Enter**:

   ```
   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/nexolunch2026/automatizacion-yt/claude/hola-5p4ttp/scripts/instalar.ps1 | iex"
   ```
4. Se abre una ventana azul que busca tus copias del programa. Cuando te pregunte, escribe
   **S** y pulsa **Enter**.

Qué hace (no borra nada):
- Pone el programa en **un solo sitio**: `C:\Users\<tú>\FacelessStudio\programa`, al lado de
  tus datos (`FacelessStudio\datos`).
- **Mueve** las copias viejas y los `.zip` descargados a `FacelessStudio\copias_viejas`. Cuando
  compruebes que todo está bien, puedes borrar esa carpeta.
- Crea en el escritorio **Faceless Studio**, **JARVIS** y **Actualizar Faceless Studio**.
  **Usa siempre esos accesos directos.**

### Paso 2 — La primera vez
- Si aparece un aviso azul de Windows («Windows protegió su PC»): pulsa **Más información** →
  **Ejecutar de todas formas**.
- Se abre una **ventana negra**. **No la cierres**: es el motor del programa. La primera vez
  tarda unos minutos; las siguientes, segundos.
- Se abre solo tu **navegador** con el programa. Si no se abre, escribe en el navegador:
  `127.0.0.1:8000`

### Paso 3 — Para tener la última versión
Doble clic en **Actualizar Faceless Studio** (en el escritorio). Tus datos no se tocan.

### Paso 4 — Crear las cuentas
1. Pulsa **Crea tu cuenta**, elige un usuario y una contraseña.
2. Tu amigo hace lo mismo con la suya. Solo se pueden crear **2 cuentas**.

### Paso 5 — Conectar Gemini (para la investigación automática)
1. En el programa, pulsa **Configuración** (arriba).
2. Sigue los pasos que aparecen ahí para conseguir la clave gratis y pégala.
3. Abre un proyecto y pulsa **Investigar el tema**.

### Paso 6 (opcional) — JARVIS en tu celular
Pulsa **🤖 JARVIS** (arriba) y sigue los pasos para crear tu bot de Telegram.
Después podrás escribirle o mandarle notas de voz desde el móvil:
*«hazme un vídeo sobre la caída de Kodak»*, *«ideas»*, *«estado»*,
*«cola: Nokia, Blockbuster»*. Te avisa en cada paso y te manda un avance del vídeo.

### Paso 7 (opcional) — Modo JARVIS, como en Iron Man
Doble clic en **`JARVIS`** (al lado de `Iniciar`). Se abre una pantalla futurista a
pantalla completa:
- **👏👏 Dos palmadas** y despierta: te saluda, te dice la hora, el clima, tus tareas
  y cómo va la producción.
- Háblale: *«anota: comprar micrófono»*, *«qué tengo hoy»*, *«hazme un vídeo sobre Nokia»*,
  *«el dos»* (para elegir enfoque), *«gracias Jarvis»* (vuelve a dormir).
- La primera vez entra con tu usuario y **permite el micrófono**.
- Para que se encienda solo al prender el ordenador: doble clic en **`JARVIS al encender`**.
- **Voz:** habla con una voz neuronal de Microsoft (gratis) con «efecto JARVIS»: más
  grave, con un toque metálico y eco suave. En ⚙ puedes elegir la voz (Álvaro, Jorge,
  Gonzalo…), quitar el efecto o usar una voz de tu cuenta de ElevenLabs.
- Si le mandas una **nota de voz por Telegram**, te contesta también con una nota de voz.
- Sabe mucho más: *«¿cómo va el canal?»* (suscriptores y meta de monetización),
  *«radar»* (marcas en apuros esta semana → un toque y lo convierte en vídeo),
  *«noticias»*, *«dólar»*, *«clima»*, *«dato curioso»*, *«estadísticas»*.
- Recordatorios y temporizadores: *«recuérdame a las 5 llamar a Juan»*,
  *«temporizador de 10 minutos»* (suena en la pantalla y llega por Telegram).
- Tu entrenador del canal: *«¿qué hago ahora?»* (el siguiente paso de cada vídeo, con un
  botón para hacerlo), *«¿cuánto me falta para monetizar?»* (suscriptores, horas vistas,
  fecha estimada y consejos) y *«revisa el vídeo de Nokia»* (la nota del control de calidad).
  Al terminar la versión final te dice si ya se puede subir.
- *«Plan de la semana»*: qué vídeo subir y qué Shorts publicar cada día (lunes, miércoles y
  sábado), y 30 minutos para aprender. Elige tu día con *«publico los jueves a las 18»*;
  el resumen de la mañana te dice lo que toca publicar hoy.
- Abre cosas: *«abre YouTube Studio»*, *«busca la historia de Kodak»*, *«pon música lofi»*,
  *«abre el proyecto de Nokia»*. Y recuerda la conversación para seguir el hilo.

### Aprender de los mejores
En `docs/aprender-de-los-mejores.md` tienes una guía con los canales que mejor hacen
documentales de marcas, qué hacen en los primeros 30 segundos, títulos y miniaturas,
cuánto paga cada nicho, 36 ideas de vídeo y cursos gratis para aprender. Pídele a JARVIS
**«banco de ideas»**, **«ideas de España»** o **«ideas de Latinoamérica»**.

### Control de calidad (antes de subir)
En cada proyecto, la pestaña **Control de calidad** te da una nota de 0 a 100 y te dice si
el vídeo podrá llevar anuncios: duración, palabras que quitan anuncios, si se parece
demasiado a otro vídeo tuyo, licencias, aviso de imágenes de IA, gancho, ritmo, miniatura y
Shorts. Cada aviso trae el botón para ir a arreglarlo. JARVIS también te lo dice si pulsas
**🔎 ¿Se puede monetizar?**. El plan de próximas mejoras está en `docs/plan-monetizacion.md`.

### Rendimiento (cuando ya publicas)
En **📈 Rendimiento** ves las visitas, «me gusta» y comentarios de cada vídeo, cómo
crecen día a día y cuál va mejor. Las cifras se guardan solas cada 3 horas, JARVIS te
avisa de los logros (100, 500, 1.000 visitas… o suscriptores) y con **«Analizar ahora»**
te dice qué funcionó, qué mejorar y qué temas hacer después.

### Para apagarlo
Cierra la **ventana negra**.

---

## Cómo actualizar a una versión nueva
1. **Cierra la ventana negra** del programa.
2. Haz **doble clic** en **`Actualizar`** (está al lado de `Iniciar`).
3. Espera a que diga **«¡Listo!»** y pulsa una tecla para cerrar.
4. Haz doble clic en **`Iniciar`**. La versión nueva aparece arriba a la izquierda.

Tus cuentas, proyectos y claves **no se tocan**. Además, antes de actualizar se guarda
una copia de seguridad en `FacelessStudio\copias_de_seguridad`.

---

## Si algo sale mal
- **La ventana negra se cierra sola o muestra un error:** haz una captura de pantalla
  y envíasela a Claude.
- **El navegador dice que no puede conectar:** asegúrate de que la ventana negra sigue abierta.

## Dónde se guardan tus datos
En **`C:\Usuarios\<tu usuario>\FacelessStudio`** (carpeta `datos`): cuentas, proyectos,
vídeos y claves. Está fuera de la carpeta del programa y de OneDrive, así que da igual
qué copia del programa abras: siempre verás los mismos datos. **No la borres.**

Cada día se guarda una **copia de seguridad** pequeña (proyectos, guiones y claves; sin
vídeos) en tu OneDrive, carpeta `FacelessStudio-copias` (o, si no tienes OneDrive, en
`FacelessStudio\copias_de_seguridad`). Dentro de cada copia hay instrucciones para restaurar.

---

<details>
<summary>Información técnica (no hace falta para usarlo)</summary>

- Diseño completo: [`docs/00-diseno-plataforma.md`](docs/00-diseno-plataforma.md)
- Python + FastAPI, páginas HTML con Jinja2, base de datos SQLite en `datos/`.
- `Iniciar.bat` instala [uv](https://docs.astral.sh/uv/) si falta y ejecuta `uv run python -m app`.
- Tests: `uv run pytest` · Lint: `uv run ruff check .`

</details>
