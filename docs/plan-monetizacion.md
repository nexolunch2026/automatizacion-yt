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
- [ ] **JARVIS útil en el día a día**: conversiones y cálculos, traducir frases, recetas
  y cantidades (Simón trabaja en cocina), listas de la compra y notas largas por voz.
- [x] **JARVIS con más habilidades en el PC** (0.34.0): abrir carpetas y programas de Windows,
  subir/bajar volumen, poner y parar música, y avisos en pantalla.
- [ ] **Guion más humano**: control de calidad de frases demasiado largas, repeticiones y
  palabras de relleno, con botón para reescribir solo esas frases.
- [ ] **Shorts que llevan al vídeo largo**: gancho propio en los primeros 2 s, texto en
  pantalla y frase final que invite a ver el documental completo.
- [ ] **Banco de ideas más grande**: llegar a 80 historias reales (sobre todo de España y
  Latinoamérica) y marcar las que ya se hicieron.
- [ ] **Pantalla JARVIS**: panel con el plan de la semana y la nota de monetización.
- [ ] **Ideas con demanda real**: cruzar el radar de marcas con lo que más se busca y con
  lo que mejor te ha funcionado en Rendimiento.
- [ ] **Retención con datos**: en Rendimiento, apuntar el % de gente que sigue al minuto 1
  y a la mitad (de YouTube Studio) y que el próximo guion refuerce esas partes.
- [ ] **Biblioteca de música** con su licencia guardada, para que el control de calidad
  la dé por buena.

Necesitan a Simón (no se hacen solas por la noche): subir a YouTube como borrador privado
(hay que conectar su cuenta de Google) y leer la retención automática de YouTube
Analytics.
