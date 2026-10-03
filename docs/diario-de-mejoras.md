# Diario de mejoras

Lo que se ha hecho en cada sesión, explicado para Simón. Lo más nuevo, arriba.

## 2026-10-03 — Versión 0.33: JARVIS se calla si le hablas y no se inventa que no puede

- **Se calla si le hablas** mientras habla, o si dices «para», «cállate», «silencio» o
  «Jarvis». Ignora su propia voz (solo se corta con palabras que él no está diciendo).
  Se puede apagar en ⚙ Ajustes.
- **No se queda callado buscando**: si tarda, dice enseguida «Un momento, lo busco».
- **Entiende pedidos en cualquier parte de la frase** («Exactamente, necesito que me digas
  qué películas hay…») y los busca directamente en Google.
- Si la IA intentaba contestar «mis sistemas no pueden acceder», ahora busca de verdad.
- Para el cine busca la cartelera de Procinal y Cinépolis en Rionegro y los estrenos de la
  semana, y recomienda una película.

## 2026-10-03 — Versión 0.32: JARVIS más rápido y concreto con las preguntas

- Las preguntas claras («¿qué película me recomiendas…?», «¿dónde puedo comer…?») van
  directas a buscar en Google: un viaje menos a Gemini.
- Busca sin «pensar» (contesta antes); si no se puede, en modo normal.
- Ya no consulta tu canal de YouTube en cada pregunta.
- Para planes (cine, restaurantes, eventos) busca en **tu ciudad** opciones de hoy con
  horarios y precios y te recomienda una, en vez de decirte «revise la cartelera».
- Arreglado: en las preguntas no recordaba la conversación («¿y a qué hora es?»).

## 2026-10-03 — Versión 0.31: JARVIS no se queda sin responder

- Si Gemini rechaza el «modo rápido», JARVIS repite la pregunta en modo normal.
- Si la búsqueda de Google no está disponible, responde con lo que sabe Gemini y avisa
  «Sin buscar en Google».
- Si aun así algo falla, enseña el **detalle técnico** para que Claude lo arregle a la
  primera, y la pantalla ya no dice «No puedo conectar con el estudio» cuando el fallo es
  otro.

## 2026-10-03 — Versión 0.30: despertar a JARVIS con su nombre

- En la pantalla JARVIS, mientras duerme, basta con decir **«Jarvis»** para despertarlo
  (además de las palmadas, tocarlo o la barra espaciadora).
- Si lo dices todo seguido, **«Jarvis, ¿qué hora es?»**, contesta directamente.
- Se puede apagar en ⚙ Ajustes → «Despertar diciendo Jarvis».
- Ya seguía escuchando tras responder (1 minuto) para continuar la conversación.

## 2026-10-03 — Versión 0.29: JARVIS sabe de todo

- **Pregúntale lo que sea** (cultura, noticias, deportes, precios, cómo hacer algo…):
  JARVIS lo busca en Google y te contesta, diciendo dónde lo buscó.
- **Memoria**: «recuerda que…» y lo tiene en cuenta siempre; «¿qué sabes de mí?» lo
  enseña.
- Si Gemini falla (por ejemplo, por el límite gratis por minuto), JARVIS te dice qué
  pasó en vez de «No te entendí bien».
- «Aprender de un vídeo» gasta unas 4 veces menos del límite gratis de Gemini, para que
  JARVIS no se quede sin respuesta mientras analizas un vídeo.

## 2026-10-03 — Versión 0.28: JARVIS más rápido

- Para entender lo que le dices, JARVIS ya no le pide a Gemini que «piense» antes de
  responder: es lo que más tardaba.
- Ya no pregunta a Google la lista de modelos en cada mensaje (la guarda unas horas).
- En la pantalla JARVIS, debajo de lo que dijiste, aparece **cuánto tardó** en responder
  («respondí en 1,8 s»), para medir si va bien.

## 2026-10-03 — Versión 0.27: aprender de un vídeo

- Menú nuevo **🎓 Aprender**: pegas el enlace de un vídeo de YouTube y Gemini lo **ve
  entero** desde tu ordenador (gratis, varias horas de vídeo al día).
- Te devuelve **lo bueno**, **cómo aplicarlo a tu canal**, **lo que no conviene** (normas
  de YouTube) e **ideas de vídeo**. Todo queda guardado.
- Botón **📌 Aplicar en mis guiones**: los guiones nuevos tienen en cuenta esa lección.
- También por Telegram: mándale a JARVIS el enlace y te responde con el resumen.

## 2026-10-03 — Versión 0.26: listo para «Probar y comparar»

- En **Publicación** hay una tarjeta nueva, **🧪 Probar y comparar**, con 3 títulos
  distintos (cada uno con su estilo y por qué puede funcionar) y las miniaturas para
  descargar de una en una.
- Te avisa si dos títulos se parecen demasiado (la prueba no serviría), si un título es
  tan largo que se corta en el móvil o si una miniatura repite el título.
- Explica cómo decide YouTube: gana la opción con **más tiempo visto**, no solo más clics.
- Cuando YouTube te active la función, solo tienes que copiar y subir.

## 2026-10-03 — Versión 0.25: variedad visual

- En **Vídeo** hay un selector nuevo, **Tono de color**: Cine, Cálido, Frío, Archivo
  (tono antiguo, ideal para historias de hace décadas) y Nítido.
- En **Automático** (lo normal), cada vídeo nuevo usa el tono que hace más tiempo que no
  usas, y la **música** también se turna («Automática (la que menos has usado)»).
- La vista previa y la versión final del mismo vídeo salen siempre con el mismo tono.
- Los Shorts usan el mismo tono que su vídeo largo.
- El **Control de calidad** avisa si un vídeo repite el tono y la música del anterior.
- Los subtítulos y el rojo de la marca no cambian: son la identidad del canal.

## 2026-10-03 — Versiones 0.19 a 0.24

- 0.19: pestaña **Control de calidad** con nota de monetización de 0 a 100.
- 0.20: JARVIS entrenador: «¿qué hago ahora?», «¿cuánto me falta para monetizar?» y
  «revisa el vídeo de…».
- 0.21: 5 estructuras de guion que se turnan, vídeos de 10–15 min por defecto y ayuda con el
  plan gratis de ElevenLabs.
- 0.22: lo aprendido de los mejores canales en los guiones, títulos y miniaturas; banco de
  36 historias reales; guía `docs/aprender-de-los-mejores.md`.
- 0.23: «plan de la semana» en JARVIS.
- 0.24: instalador que deja el programa en un solo sitio y ordena las copias viejas.
