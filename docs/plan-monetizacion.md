# Plan: el mejor programa para hacer vídeos de YouTube que se puedan monetizar

Boceto de mejoras para Faceless Studio. La idea central: **YouTube no paga por vídeos
automáticos, paga por vídeos que la gente quiere ver y que aportan algo propio**. La
automatización sirve para ahorrar horas, no para sustituir tu criterio.

## Lo que YouTube exige (resumen)

1. **Entrar al Programa de Socios**: 1.000 suscriptores y 4.000 horas vistas en 12 meses
   (o 10 millones de visitas en Shorts en 90 días).
2. **Contenido no auténtico** (antes «repetitivo»): no paga canales que publican vídeos
   hechos en serie con la misma plantilla, o que solo leen información sin aportar análisis.
3. **Contenido reutilizado y derechos**: imágenes, vídeos y música con licencia.
4. **Apto para anunciantes**: palabrotas o temas delicados en el título, la miniatura o los
   primeros segundos limitan los anuncios.
5. **Contenido alterado o sintético**: marcarlo al subir si hay imágenes realistas de IA.
6. **Ingresos**: desde 8 minutos se pueden poner anuncios a mitad del vídeo.

## Fase 1 — hecha en la versión 0.19.0

- **Control de calidad** (pestaña nueva): nota de 0 a 100 con semáforo y qué pulsar para
  arreglar cada punto. Revisa: duración (anuncios a mitad), palabras que quitan anuncios,
  parecido con tus otros vídeos, datos con fuente, si has retocado el guion, licencias de
  imágenes, aviso de IA, voz de ElevenLabs, música, gancho de los primeros 30 s, ritmo de
  escenas, escenas solo con texto, título, capítulos, miniatura y Shorts.
  No gasta nada: no usa IA ni internet.
- **Guiones pensados para monetizar**: la IA ahora debe aportar análisis propio (por qué
  pasó y qué lección deja), empezar sin saludar, dejar una intriga al final de cada parte y
  usar lenguaje apto para anunciantes.
- **JARVIS**: al mandarte los textos para YouTube añade el botón «🔎 ¿Se puede monetizar?».

## JARVIS entrenador — hecho en la versión 0.20.0

- **«¿Qué hago ahora?»**: el siguiente paso de cada vídeo a medias, con un botón que lo hace.
- **«¿Cuánto me falta para monetizar?»**: suscriptores y ritmo diario, fecha estimada para
  llegar a 1.000, horas vistas estimadas (visitas × duración × % visto) y 3 consejos.
- **«Revisa el vídeo de…»**: la nota del control de calidad por Telegram o por voz.
- La versión final del vídeo llega con la nota de monetización; el resumen de la mañana y
  la pantalla JARVIS dicen el siguiente paso, y piden revisar antes de subir si hace falta.
- Las ideas llegan con formatos distintos para que el canal no parezca hecho en serie.

## Variedad, vídeos largos y ElevenLabs gratis — hecho en la versión 0.21.0

- **Estructuras que se turnan**: cronológica, ascenso y caída, los errores clave, rivalidad
  e investigación. En «Automática» cada guion usa la que hace más tiempo que no se usa en
  el canal; el control de calidad avisa si repites la del último vídeo.
- **10–15 min por defecto** en los proyectos nuevos (anuncios a mitad del vídeo).
- **ElevenLabs con el plan gratis**: la página Voz dice cuántos vídeos te alcanzan este mes
  (normal y Ahorro); la descripción cita a ElevenLabs como pide ese plan; el control de
  calidad y JARVIS (al acercarte a 1.000 suscriptores) te recuerdan pagar el plan más
  barato justo antes de solicitar la monetización.

## Aprender de los mejores — hecho en la versión 0.22.0

- Guía `docs/aprender-de-los-mejores.md`: referentes, técnicas, nichos, ideas y cursos.
- Guiones con el gancho en 3 tiempos, giro hacia el segundo 30 y la sección fija «La
  lección de la marca» (la firma del canal); títulos de 60 caracteres como mucho y
  miniaturas que completan el título.
- Banco de 36 historias reales en JARVIS (también de reserva si Gemini falla).
- El aviso de IA del control de calidad solo pide marcar lo que parezca real.

## Plan de la semana — hecho en la versión 0.23.0

- JARVIS: «plan de la semana» (vídeo largo el día elegido, Shorts lunes, miércoles y
  sábado, y una tarea de aprendizaje de 30 minutos); «publico los jueves a las 18» para
  cambiar el día; el resumen de la mañana avisa de lo que toca publicar hoy.

## Cualquier nicho (pedido de Simón) — fases 1–3 hechas (versiones 0.39 y 0.40)

- [x] **Fase 1 — Ficha del nicho**: cada canal tiene su ficha (formato, público, tono,
  4–5 estructuras de guion, sección final fija, consejos de títulos y miniaturas, riesgos).
  La crea Gemini una vez; los canales de marcas usan la de siempre; sin IA, una general.
  Guion, estrategia y miniaturas la usan.
- [x] **Fase 2 — Ideas y noticias del nicho**: ideas, radar de noticias y dato curioso del
  día salen de la ficha; el banco de 36 historias solo para canales de marcas.
- [x] **Fase 3 — Formatos y estilo** (versión 0.40.0): formato del vídeo (top/lista,
  explicación, relato o automático según la ficha; JARVIS lo deduce de «top 10…»,
  «explica…») y color propio por canal en subtítulos, textos, gráficos, miniaturas y Shorts.
- [ ] **Fase 4 — Probar con nichos muy distintos** con Gemini de verdad (misterios,
  finanzas personales, historia) y ajustar lo que salga raro.

## Lista de próximas mejoras

La sesión automática de cada noche coge **la primera sin marcar**, la hace, la marca con
`[x]` y anota lo hecho en `docs/diario-de-mejoras.md`. Simón puede reordenar la lista o
añadir ideas cuando quiera (escribiéndoselo a Claude).

- [x] **Variedad visual** (0.25.0): turnar entre vídeos el estilo de subtítulos, la música y el
  «look» (como ya se turnan las estructuras), y que el control de calidad avise si el vídeo
  se parece demasiado al anterior.
- [x] **Preparado para «Probar y comparar»** (0.26.0): en Publicación, 3 títulos y las 3
  miniaturas listos para el A/B de YouTube, con cuál probar y por qué.
- [x] **JARVIS se deja interrumpir hablando** (0.33.0) (ya sigue escuchando 1 minuto tras
  responder; falta poder cortarle con la voz mientras habla, sin que se oiga a sí mismo).
- [x] **JARVIS se despierta con su nombre** (0.30.0): además de las palmadas, decir «Jarvis»
  (reconocimiento en el navegador, sin gastar Gemini).
- [x] **JARVIS útil en el día a día** (0.35.0): conversiones y cálculos, traducir frases, recetas
  y cantidades (Simón trabaja en cocina), listas de la compra y notas largas por voz.
- [x] **JARVIS con más habilidades en el PC** (0.34.0): abrir carpetas y programas de Windows,
  subir/bajar volumen, poner y parar música, y avisos en pantalla.
- [x] **Guion más humano** (0.58.0): control de calidad de frases demasiado largas, repeticiones y
  palabras de relleno, con botón para reescribir solo esas frases.
- [x] **Versión para compartir**: perfil por instalación (nombre, canal, nicho, país),
  bienvenida para gente nueva y línea de instalación para pasar.
- [x] **Investigar en YouTube**: buscar y ver varios vídeos de un tema y juntar lo
  aprendido en un informe (🎓 Aprender o «investiga en YouTube…» a JARVIS).
- [x] **Shorts que llevan al vídeo largo**: gancho propio en los primeros 2 s, texto en
  pantalla y frase final que invite a ver el documental completo.
- [ ] **Banco de ideas más grande**: llegar a 80 historias reales (sobre todo de España y
  Latinoamérica) y marcar las que ya se hicieron.
- [ ] **Lo que pide tu audiencia**: con la clave de YouTube, leer los comentarios de tus
  vídeos y sacar preguntas y temas que pide la gente (ideas nuevas y respuestas para el
  comentario fijado), en Rendimiento y por JARVIS.
- [x] **Miniatura legible en el móvil** (0.65.0): comprobar el tamaño y el contraste del texto de
  cada miniatura vista a 168 px de ancho y avisar si no se lee bien.
- [x] **Alertas de referencias** (0.64.0): JARVIS avisa por Telegram cuando un vídeo de tus canales de
  referencia se dispara (más de ×3 su media), con el botón «Hacer mi versión».
- [x] **Pantalla JARVIS** (0.42.0): panel «Esta semana» con el plan de la semana y el camino a
  la monetización (suscriptores, horas, fecha estimada y un consejo).
- [x] **Títulos y etiquetas con búsquedas reales** (0.45.0): en Publicación, lo que la gente
  escribe en YouTube va primero en las etiquetas y avisa si el título no lo usa.
- [x] **Ideas con demanda real** (0.44.0): las ideas de JARVIS se inspiran en el radar del
  nicho y en lo que mejor funcionó, y se ordenan por lo que la gente busca en YouTube.
- [x] **Retención con datos** (0.41.0): en Rendimiento, apuntar el % de gente que sigue a los
  30 s y a la mitad (de YouTube Studio) y que el próximo guion refuerce esas partes.
- [x] **Biblioteca de música** (0.43.0) con su licencia guardada, para que el control de
  calidad la dé por buena y la atribución vaya sola a los créditos.

En pausa hasta que Simón lo pida (no hacer por la noche): **clips con Veo desde Google
Opal** (texto para copiar en cada escena y «Subir clip» en Visuales). Ya está empezado en la
rama `claude/clips-opal`: falta probarlo con Simón.

Necesitan a Simón (no se hacen solas por la noche): subir a YouTube como borrador privado
(hay que conectar su cuenta de Google) y leer la retención automática de YouTube
Analytics.
