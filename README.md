# Faceless Studio

Programa para crear vídeos de YouTube sin salir en cámara.
Por ahora tiene: **cuentas para 2 personas, canales, proyectos de vídeo e
investigación automática del tema con fuentes** (usa Gemini, gratis).
La creación automática de los vídeos se irá añadiendo poco a poco.

---

## Cómo instalarlo en Windows (paso a paso)

### Paso 1 — Descargar el programa
1. Abre este enlace (tienes que haber iniciado sesión en GitHub):
   **https://github.com/nexolunch2026/automatizacion-yt/archive/refs/heads/claude/hola-5p4ttp.zip**
2. Se descarga un archivo **.zip** (una carpeta comprimida) en tu carpeta **Descargas**.

### Paso 2 — Descomprimir
1. Abre la carpeta **Descargas**.
2. Haz **clic derecho** sobre el archivo `.zip` → **Extraer todo…** → **Extraer**.
3. Se crea una carpeta normal. Puedes moverla donde quieras, por ejemplo al **Escritorio**.

### Paso 3 — Encender el programa
1. Entra en la carpeta.
2. Haz **doble clic** en el archivo **`Iniciar`** (o `Iniciar.bat`).
3. Si aparece un aviso azul de Windows («Windows protegió su PC»):
   pulsa **Más información** → **Ejecutar de todas formas**.
4. Se abre una **ventana negra**. **No la cierres**: es el motor del programa.
   - La **primera vez** tarda unos minutos porque descarga lo que necesita.
   - Las siguientes veces arranca en segundos.
5. Se abre solo tu **navegador** con el programa.
   Si no se abre, escribe en el navegador: `127.0.0.1:8000`

### Paso 4 — Crear las cuentas
1. Pulsa **Crea tu cuenta**, elige un usuario y una contraseña.
2. Tu amigo hace lo mismo con la suya. Solo se pueden crear **2 cuentas**.

### Paso 5 — Conectar Gemini (para la investigación automática)
1. En el programa, pulsa **Configuración** (arriba).
2. Sigue los pasos que aparecen ahí para conseguir la clave gratis y pégala.
3. Abre un proyecto y pulsa **Investigar el tema**.

### Para apagarlo
Cierra la **ventana negra**.

---

## Cómo actualizar a una versión nueva
1. **Cierra la ventana negra** del programa.
2. Haz **doble clic** en **`Actualizar`** (está al lado de `Iniciar`).
3. Espera a que diga **«¡Listo!»** y pulsa una tecla para cerrar.
4. Haz doble clic en **`Iniciar`**. La versión nueva aparece arriba a la izquierda.

Tus cuentas, proyectos y claves **no se tocan**. Además, antes de actualizar se guarda
una copia de seguridad en la carpeta `copias_de_seguridad`.

---

## Si algo sale mal
- **La ventana negra se cierra sola o muestra un error:** haz una captura de pantalla
  y envíasela a Claude.
- **El navegador dice que no puede conectar:** asegúrate de que la ventana negra sigue abierta.

## Dónde se guardan tus datos
En la carpeta `datos`, dentro de la carpeta del programa. **No la borres**: ahí están
las cuentas, los canales y los proyectos.

---

<details>
<summary>Información técnica (no hace falta para usarlo)</summary>

- Diseño completo: [`docs/00-diseno-plataforma.md`](docs/00-diseno-plataforma.md)
- Python + FastAPI, páginas HTML con Jinja2, base de datos SQLite en `datos/`.
- `Iniciar.bat` instala [uv](https://docs.astral.sh/uv/) si falta y ejecuta `uv run python -m app`.
- Tests: `uv run pytest` · Lint: `uv run ruff check .`

</details>
