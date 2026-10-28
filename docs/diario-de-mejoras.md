# Diario de mejoras

Lo que se ha hecho en cada sesión, explicado para Simón. Lo más nuevo, arriba.

## 2026-10-28 — Versión 0.91.1: revisión de salud

Revisión de los cambios de la semana (0.85 a 0.91) con los revisores de errores escondidos,
de Python y de seguridad. Seguridad: todo bien. Se arreglaron tres fallos:

- **«¿Qué miniatura ganó?»**: si rehacías las miniaturas **después de publicar** (por
  ejemplo con el botón del aviso de CTR), JARVIS preguntaba por las nuevas, aunque YouTube
  había probado las de antes, y se apuntaba una ganadora equivocada. Ahora en ese caso no
  pregunta.
- Un vídeo con datos raros en sus miniaturas **frenaba los avisos de todos los demás**.
  Ahora se salta solo ese, y llegan como mucho 2 avisos cada hora.
- **«La primera frase es vaga»** no salía con frases como «Aquel día todo cambió» o «Hace
  años, nadie imaginaba…». Ahora sí; la marca del título al empezar («Kodak inventó…») sigue
  contando como dato concreto.
- Los avisos de CodeQL de GitHub siguen sin poder leerse desde aquí (GitHub no da permiso).

## 2026-10-28 — Versión 0.91: las miniaturas aprenden de las que ganaron

- Cuando apuntas en JARVIS qué miniatura ganó en «Probar y comparar», el programa ya lo
  **usa al hacer las miniaturas nuevas**.
- Si en tu canal suelen ganar las miniaturas **con una cifra** (o **solo con palabras**),
  Gemini lo sabe y escribe así al menos dos de los tres textos.
- La **posición del texto** (izquierda, abajo o centro) ahora se **turna** entre vídeos, para
  que en «Probar y comparar» no gane siempre la misma solo por ir en la primera miniatura.
  Así lo que te dice JARVIS sobre la posición es de fiar.
- Hace falta tener al menos **2 ganadoras apuntadas**; antes de eso todo sigue igual.
- Ideas nuevas en la lista: «Tarjeta a mitad del vídeo» y «Título y miniatura aptos para
  anunciantes».

## 2026-10-27 — Versión 0.90: ¿qué miniatura ganó?

- «**Probar y comparar**» de YouTube Studio prueba tus 3 miniaturas unas dos semanas y te
  dice cuál gana.
- **Dos semanas después** de publicar, JARVIS te escribe por **Telegram** con las 3
  miniaturas y te pregunta cuál ganó. Pulsa **«🏆 La 1/2/3»** (o **«🤷 No lo probé»**).
- Con dos o más apuntadas, JARVIS te dice **qué estilo gana en tu canal** (dónde va el
  texto y si lleva una cifra), para hacer las próximas así.
- Avisa una vez por vídeo y solo si el vídeo tiene 2 o 3 miniaturas para comparar.
- Ideas nuevas: la lista ya está hecha; la próxima noche se añaden otras 3.

## 2026-10-26 — Versión 0.89: subtítulos que se leen en el móvil

- El archivo de **subtítulos (.srt)** que subes a YouTube ahora se hace en trozos de **2
  líneas cortas como mucho** (lo que cabe bien en el móvil), cortando donde la voz hace
  una pausa (en los puntos y las comas).
- Cada trozo dura lo que tarda la voz en decirlo, palabra a palabra, así no se adelanta
  ni se atrasa.
- En la página **Vídeo**, debajo del vídeo, sale 📝 si los subtítulos se leen bien o
  cuántos trozos se leen mal (demasiado largos o muy deprisa).
- Si tienes un vídeo montado antes de esta versión, **vuelve a montarlo** para que sus
  subtítulos salgan con el formato nuevo.

## 2026-10-25 — Versión 0.88.1: radar de historias

Tres historias nuevas y recientes en el **banco de historias** (pídeselas a JARVIS con
«banco de ideas»):

- **Getty Images** (Mundo, ascenso y caída): el gran archivo de fotos entró en quiebra el
  21 de octubre con unos 1.460 millones de dólares de deuda (y la IA como telón de fondo).
- **Inside** (España, ascenso y caída): la cadena de moda murciana pidió concurso en enero
  con 69 millones de deuda; ahora hay una oferta para salvar 184 tiendas.
- **TV Azteca** (Latinoamérica, investigación): la televisora de Salinas Pliego, en concurso
  mercantil desde julio, con pelea con sus acreedores en tres países.

Fuentes: [Getty, SEC](https://www.sec.gov/Archives/edgar/data/0001898496/000121390026111193/ea030922501ex99-1.htm),
[Reuters vía GV Wire](https://gvwire.com/2026/10/21/getty-images-files-for-us-bankruptcy-advances-restructuring-plan/),
[Bloomberg](https://bloomberg.com/news/articles/2026-10-21/getty-files-for-bankruptcy-in-process-that-will-take-it-private),
[Modaes](https://www.modaes.com/empresas/inside-abre-etapa-strong-capital-and-founds-rescata-la-empresa-con-una-oferta-vinculante),
[Lexpress Franchise](https://lexpress-franchise.com/es/ultimas-noticias/inside-oferta-compra-para-sacarla-concurso-acreedores-strong-capital/),
[Atlántico Hoy](https://www.atlanticohoy.com/empresas/inside-busca-comprador-cadena-ropa-presente-en-canarias-encara-oferta-474-millones_1568929_102.html),
[Expansión](https://expansion.mx/empresas/2026/07/07/tv-azteca-es-declarada-oficialmente-concurso-mercantil),
[El Imparcial](https://www.elimparcial.com/dinero/2026/07/07/jueza-declara-a-tv-azteca-de-ricardo-salinas-pliego-en-concurso-mercantil-tendra-hasta-365-dias-para-evitar-la-quiebra/),
[La Jornada](https://www.jornada.com.mx/noticia/2026/09/24/politica/filiales-de-tv-azteca-presentan-demandan-de-concurso-mercantil).

## 2026-10-25 — Versión 0.88: el ritmo de la voz

- Una narración demasiado **deprisa** cuesta seguirla; demasiado **lenta**, aburre. En
  documental suena natural entre **140 y 170 palabras por minuto**.
- El **control de calidad** ahora mide la voz que ya grabaste y te dice a cuántas palabras
  por minuto va (✅ si está bien). Solo cuenta lo grabado con el texto actual: si cambiaste
  un párrafo y no lo regrabaste, ese no se mide.
- Si va muy deprisa (más de 190) o muy lenta (menos de 120), sale ⚠️ con el arreglo: en
  **Voz**, te dice qué velocidad elegir («Lenta», «Normal» o «Rápida») según la que ya
  tienes; si ya está al límite, te dice qué cambiar en el guion.
- Ideas nuevas en la lista: «Subtítulos que se leen en el móvil» y «¿Qué miniatura ganó?».

## 2026-10-24 — Versión 0.87: JARVIS avisa si la miniatura no convence

- El **CTR** es cuántas personas de cada 100 hacen clic al ver tu miniatura. Lo copias de
  YouTube Studio en **Rendimiento**.
- Si un vídeo lleva **7 días o más** y su CTR es **menor del 3 %**, JARVIS te escribe por
  **Telegram**: cambiar la miniatura es lo más rápido para conseguir más clics.
- El mensaje trae el botón **«🖼️ Ver mis 3 miniaturas»** para elegir otra (o **«🔄 Hacer 3
  miniaturas»** si ese vídeo aún no tenía). Luego súbela tú en YouTube Studio → Contenido →
  el vídeo → Miniatura.
- Avisa **una vez por vídeo** (como mucho 2 avisos cada hora) y nunca cambia nada en
  YouTube por su cuenta.

## 2026-10-23 — Versión 0.86: la primera frase engancha con un dato

- La **primera frase** del vídeo decide si la gente se queda. Una cifra, un año o un nombre
  (la marca) enganchan mucho más que «Esta es una historia increíble». Una pregunta solo
  cuenta si también es concreta («¿Cómo perdió Kodak 30.000 millones?»).
- El **control de calidad** ahora mira la primera frase del guion y avisa ⚠️ **«La primera
  frase es vaga»** si no tiene nada concreto, y te la enseña.
- Arreglo: cambia esa frase por el dato más sorprendente de la historia (o pulsa «Otra
  forma» en ese párrafo del **Guion**).
- Los guiones nuevos ya empiezan así: Gemini pone algo concreto en la primera frase.

## 2026-10-22 — Versión 0.85: la miniatura añade algo al título

- En YouTube, el **título y la miniatura se ven juntos**. Si dicen lo mismo, se desperdicia
  uno de los dos: la miniatura debería añadir algo (una cifra, una emoción, una pregunta).
- En la página **Miniatura**, debajo de cada una, ahora sale 🏷️ **«Añade algo al título»**
  o **«Repite el título»** con las palabras que repite.
- El **control de calidad** también avisa si la miniatura que elegiste repite el título.
  Arreglo: cambia el texto en Miniatura o elige otra de las 3.
- Gemini ya recibe la instrucción de no repetir el título al escribir los textos.
- Ideas nuevas en la lista: «Gancho con un dato concreto» y «Miniatura floja según el CTR».

## 2026-10-21 — Versión 0.84.1: revisión de salud

Revisión de los cambios de la semana (0.78 a 0.84) con los revisores de errores escondidos,
de Python y de seguridad. Seguridad: todo bien. Se arreglaron dos fallos:

- **«✅ Ya subí el Short de hoy»**: al pulsarlo, JARVIS y la página Semana te pedían
  **otro Short ese mismo día**. Ahora ese día queda hecho y el siguiente pasa al próximo
  día de Shorts. (Si lo desmarcas, hoy vuelve a tocar.)
- **El «buenos días» de JARVIS**: si fallaba algo al preparar el plan del día, el mensaje
  de la mañana **no llegaba en todo el día**. Ahora llega igual, con un aviso de que el plan
  no se pudo preparar.
- Los avisos de CodeQL de GitHub siguen sin poder leerse desde aquí (GitHub no da permiso).

## 2026-10-21 — Versión 0.84: tu mejor día para publicar

- En la página **📅 Semana** hay una tarjeta nueva: **«📈 Tu mejor día para publicar»**.
- Mira tus cifras de **Rendimiento**: cuántas visitas consigue cada vídeo largo en sus
  **primeras 48 horas**, según el día de la semana en que salió.
- Si un día te va claramente mejor (al menos un 30 % más que los otros días), te lo dice y
  aparece un botón para **probar a publicar ese día** con un clic. Un solo vídeo con suerte
  no decide: hacen falta al menos 6 vídeos largos y 3 en cada día que compara.
- Si aún hay pocos vídeos, o casi siempre publicas el mismo día, te lo explica (y te
  sugiere probar otro día un par de semanas si quieres saberlo).
- Si algo falla al leer las cifras, la página Semana y JARVIS siguen funcionando igual.
- JARVIS también lo dice en **«plan de la semana»** cuando hay un día mejor.

## 2026-10-20 — Versión 0.83: final sin despedida larga

- En cuanto se oye «suscríbete», «dale a like» o «nos vemos», mucha gente **cierra el
  vídeo**, y YouTube ya no le enseña otro tuyo.
- El **control de calidad** ahora mira el final del guion: si la despedida dura **más de
  unos 12 segundos**, sale un aviso ⚠️ con cuántos segundos son.
- Arreglo: deja la despedida en **una frase** y termina con la frase que lleva a otro vídeo
  tuyo (la tienes lista en **Publicación → Pantalla final**).
- Si el final ya lleva a otro vídeo, sale ✅ «El final lleva a otro vídeo tuyo».
- Los guiones nuevos ya se escriben así: Gemini termina con esa frase, sin despedidas largas.

## 2026-10-19 — Versión 0.82: la descripción se entiende en la búsqueda

- En la búsqueda de YouTube solo se ven las **2 primeras líneas** de la descripción (unos
  150 caracteres) antes de «Mostrar más». Ahí tiene que decir **de qué va el vídeo**.
- En **Publicación**, debajo de la descripción, ahora ves **«Así se ve en la búsqueda de
  YouTube»** con un ✅ si nombra la marca del título o lo que la gente busca.
- Si no lo hace (o empieza con enlaces, hashtags o capítulos), sale ⚠️ y también un aviso en
  el **control de calidad**: pulsa «Volver a generar» o cambia la primera frase al pegarla.
- A partir de ahora Gemini escribe la primera frase de la descripción ya con la marca o el
  tema de la búsqueda principal.
- Ideas nuevas en la lista: «Final sin despedida larga» y «Mejor día para publicar».

## 2026-10-18 — Versión 0.81.1: radar de historias

Tres historias nuevas y recientes en el **banco de historias** (pídeselas a JARVIS con
«banco de ideas»):

- **Presto** (Latinoamérica, ascenso y caída): la cadena de hamburguesas colombiana entra
  en liquidación; la Superintendencia de Sociedades lo dejó en firme el 13 de octubre.
- **Publimetro** (Latinoamérica, ascenso y caída): el diario gratuito, tras 25 años en
  Chile, pidió la quiebra con casi 14.000 millones de pesos de deuda.
- **Character.AI** (Mundo, investigación): la app de chatbots, demandada en los
  tribunales, se declaró en quiebra; Disney ofreció 20 millones de dólares por una licencia.

Fuentes: [El Colombiano](https://www.elcolombiano.com/negocios/presto-liquidacion-judicial-quiebra-restaurantes-colombia-AB42342543),
[Vanguardia](https://www.vanguardia.com/colombia/2026/10/16/presto-oficializa-su-quiebra-entra-en-liquidacion-judicial-y-busca-comprador-para-evitar-el-cierre-de-sus-restaurantes/),
[Pulzo](https://www.pulzo.com/economia/restaurantes-presto-acaba-colombia-supersociedades-confirmo-quiebra-PP5332063),
[La Tercera](https://www.latercera.com/pulso/noticia/publimetro-pide-su-quiebra-y-acusa-pasivos-por-casi-14000-millones/),
[Sabes](https://sabes.cl/2026/09/15/publimetro-solicita-su-quiebra-en-chile-mantiene-deudas-por-casi-14-000-millones),
[CNN](https://edition.cnn.com/2026/10/13/tech/character-ai-bankruptcy-filing),
[Forbes](https://www.forbes.com/sites/siladityaray/2026/10/13/characterai-files-for-bankruptcy-disney-bids-20-million-after-copyright-dispute/),
[Deadline](https://deadline.com/2026/10/disney-character-ai-chapter-11-bankruptcy-1237155582/).

## 2026-10-18 — Versión 0.81: recordatorio para responder comentarios

- **Dos días después** de publicar un vídeo, JARVIS te escribe por **Telegram**: es buen
  momento para **responder los comentarios** (a YouTube le gusta y la gente vuelve).
- El mensaje trae el botón **«💬 Leer comentarios y borradores»**: JARVIS lee los
  comentarios de **ese vídeo** y te manda **borradores de respuesta** para los que tienen más «me gusta»,
  con el enlace directo a cada uno.
- Revisa cada borrador y pégalo tú en YouTube: el programa no publica nada solo.
- Avisa **una vez por vídeo**. Para leer los comentarios hace falta la clave gratuita de
  YouTube (y Gemini para los borradores). Si no puede leerlos en ese momento, te dice por
  qué y de qué día son los borradores que te enseña.

## 2026-10-17 — Versión 0.80: «Ya lo subí» para los Shorts

- El calendario de Shorts (lunes, miércoles y sábado, en la página **📅 Semana**) ya
  existía, pero siempre te proponía los mismos. Ahora **sabe cuáles ya subiste**.
- En **Shorts**, cada uno tiene un botón **«✅ Ya lo subí»** (y «deshacer» si te
  equivocas). El calendario pasa solo al siguiente.
- En el **«buenos días»** de JARVIS por Telegram, el día que toca Short, sale el botón
  **«✅ Ya subí el Short de hoy»**: lo pulsas y te dice cuál toca después.
- Si vuelves a hacer los Shorts de un vídeo, las marcas se borran (son Shorts nuevos).
- Arreglo: una prueba de las alertas de canales de referencia fallaba según la fecha; ya
  no depende del día.

## 2026-10-16 — Versión 0.79: el principio cumple lo que promete el título

- El **Control de calidad** tiene una comprobación nueva: mira si los **primeros 45
  segundos** del guion hablan de lo que **promete el título** (la marca, el hecho…).
- Si no, avisa en amarillo y te dice qué palabras del título conviene mencionar en los
  **primeros 45 segundos**. Si el título nombra una marca, tiene que salir pronto.
- Por qué: quien hace clic espera ver pronto lo del título. Si no aparece, se va enseguida
  y YouTube enseña menos el vídeo.
- Lista de mejoras: dos ideas nuevas (calendario de Shorts y recordatorio de responder
  comentarios).

## 2026-10-15 — Versión 0.78: Shorts de tus vídeos que ya funcionaron

- En **Rendimiento** hay una tarjeta nueva, **«♻️ Shorts de tus vídeos que ya
  funcionaron»**, con tus **3 vídeos con más visitas**.
- Para cada uno te dice **el siguiente paso** con un botón:
  - **«Hacer sus Shorts»** si todavía no tiene (y te avisa si se están haciendo o si fallaron);
  - **«Poner el enlace al vídeo»** para que cada Short lleve al vídeo largo;
  - **«Ver sus Shorts para subirlos»** cuando ya está todo listo.
- Consejo: sube uno cada 2 o 3 días. Cada Short trae gente nueva a un vídeo que ya sabes
  que gusta.

## 2026-10-14 — Versión 0.77.1: revisión de salud

Revisión de los cambios de la semana con los revisores automáticos (errores escondidos,
Python y seguridad). Se arreglaron 2 fallos:

- **Avisos de JARVIS que se perdían:** si uno de los avisos automáticos fallaba (por ejemplo
  el piloto automático), se perdían también los demás que estaban listos, como el «buenos
  días» o el resumen del domingo, y no volvían a enviarse. Ahora cada aviso va por su lado.
- **Aviso de la voz de respaldo:** «Revisar mi ordenador» seguía diciendo que la voz de
  Microsoft había fallado aunque ya funcionara otra vez. Ahora el aviso se quita solo en
  cuanto vuelve, y enseña el día y la hora.

Seguridad: sin problemas. Los avisos de GitHub (CodeQL) no se pueden leer desde aquí.

## 2026-10-14 — Versión 0.77: aviso cuando un vídeo despega

- Si un vídeo tuyo **recién publicado** (entre 12 y 72 horas) va **al doble de lo normal**
  en tu canal, JARVIS te avisa por **Telegram**: «🚀 ¡… está despegando!».
- Te dice cuántas visitas lleva y **qué hacer ahora**: responder comentarios, subir un
  Short que lleve a él y preparar otro vídeo del mismo estilo.
- Botones **«💡 Ideas parecidas»** y **«📈 Ver rendimiento»**.
- Avisa **una sola vez** por vídeo. Necesita al menos 2 vídeos anteriores con cifras de sus
  primeras 48 horas para saber qué es «lo normal».
- Arreglo: una prueba de JARVIS («cuánto me falta para monetizar») fallaba según el día
  en que se ejecutaba; ya no depende de la fecha.

## 2026-10-13 — Versión 0.76: JARVIS no se queda mudo

- Si la **voz de Microsoft** que usa JARVIS no responde (sin internet, o Microsoft la
  bloquea), JARVIS **habla con la voz gratuita del programa** (Piper), con su efecto de
  siempre.
- Funciona en la **pantalla de JARVIS** y en las **notas de voz de Telegram**.
- La próxima vez vuelve a probar la de Microsoft: en cuanto funcione, se oye la de siempre.
- La prueba de GitHub ahora comprueba lo importante: que **JARVIS pueda hablar**. Si
  Microsoft falla, lo apunta como aviso.
- Lista de mejoras: dos ideas nuevas (aviso cuando un vídeo despega y Shorts de tus vídeos
  que ya funcionaron).

## 2026-10-12 — Versión 0.75: resumen del domingo por Telegram

- Cada **domingo**, a la hora de tu piloto automático, JARVIS te manda por Telegram
  **cómo fue la semana** del canal.
- Te dice las **visitas** de los últimos 7 días y si **subieron o bajaron** frente a la
  semana anterior, **el vídeo que más tiró** y cuántos **suscriptores** ganaste.
- Termina con **un consejo** sencillo para la semana siguiente.
- Usa las cifras que el programa ya guarda en **Rendimiento**: empieza a llegar cuando hay
  dos semanas de datos. Con el botón **«📈 Ver rendimiento»** ves el detalle.

**Aviso:** esta versión no se ha mandado al actualizador. La prueba de GitHub que usa
servicios reales falló dos veces seguidas: la **voz de Microsoft de JARVIS** respondió
«acceso denegado» (error 403) desde los ordenadores de GitHub. No tiene que ver con esta
mejora (no toca la voz), y no hay versión nueva de la librería de la voz que lo arregle.
Si a ti también te falla la voz de JARVIS, avísale a Claude.

## 2026-10-11 — Versión 0.74.1: radar de historias

Tres historias nuevas y recientes en el **banco de historias** (pídeselas a JARVIS con
«banco de ideas»):

- **Crumbl** (Mundo, ascenso y caída): la galletería que se hizo viral en redes ha cerrado
  al menos 57 tiendas en 2026.
- **Desigual** (España, errores): en septiembre tuvo que pedir perdón por un anuncio que
  ridiculizaba Barcelona, su propia ciudad.
- **Zhoue** (Latinoamérica, ascenso y caída): la marca de ropa argentina declaró casi 6.000
  millones de pesos de deudas y pidió concurso preventivo.

Fuentes: [TheStreet](https://www.thestreet.com/retail/crumbl-cookie-chain-closes-57-locations-in-2026-franchisee-files-chapter-7-bankruptcy),
[Yahoo Finanzas](https://finance.yahoo.com/small-business/articles/crumbl-closed-57-stores-franchisees-180739687.html),
[KUTV](https://kutv.com/news/local/crumbl-cookies-closes-dozens-of-stores-amid-declining-sales-report-finds),
[eldiario.es](https://www.eldiario.es/catalunya/desigual-disculpa-polemico-anuncio-criticado-burlarse-gentrificacion-barcelona_1_13483136.html),
[Reason Why](https://www.reasonwhy.es/actualidad/desigual-polemica-retrato-barcelona-campana-ottolinger),
[The Olive Press](https://www.theolivepress.es/spain-news/2026/09/07/barcelona-desigual-advert-fury/),
[iProfesional](https://www.iprofesional.com/negocios/466310-colapsa-marca-de-ropa-femenina-con-deuda-de-6000-millones-de-pesos),
[FashionNetwork](https://pe.fashionnetwork.com/news/La-firma-argentina-de-moda-femenina-zhoue-se-declara-al-borde-de-la-quiebra,1869989.html).

## 2026-10-11 — Versión 0.74: listas de reproducción listas para copiar

- En **Rendimiento** hay una tarjeta nueva, **«📂 Listas de reproducción»** (sale cuando
  tienes 2 vídeos publicados o más).
- Agrupa tus vídeos por su **formato** (ascenso y caída, rivalidad…). Si todavía no hay
  grupos de 2, te propone una lista con **todas tus historias**.
- Cada lista trae **título y descripción con botón «Copiar»** y los vídeos en orden, del
  más viejo al más nuevo. Los que no encajan en ningún grupo van en «Más historias».
- Para qué sirve: dentro de una lista, YouTube pone **el siguiente vídeo solo**, y eso suma
  horas vistas, que es lo que cuenta para monetizar.
- En YouTube Studio: «Contenido» → «Listas» → «Nueva lista».

## 2026-10-10 — Versión 0.73: pantalla final que lleva a otro vídeo

- En **Publicación** hay una tarjeta nueva, **«🔚 Pantalla final»**: te dice qué vídeo tuyo
  poner al final para que la gente **siga viendo tu canal** (YouTube lo premia).
- Te propone hasta 2: el de **tema más parecido** y el de **más visitas**. Si aún no tienes
  cifras, el más reciente.
- Cada uno trae una **frase para el final del guion** que invita a verlo, con botón
  **«Copiar»**, y dónde ponerlo en YouTube Studio.
- Funciona con los vídeos que ya aparecen en **Rendimiento**.
- Lista de mejoras: se añadieron dos ideas nuevas para las próximas noches (listas de
  reproducción y un resumen de la semana los domingos por Telegram).

## 2026-10-09 — Versión 0.72: banco de historias para cualquier canal

- Si tienes un canal que **no es de marcas** (misterios, finanzas, historia…), al pedir a
  JARVIS **«banco de historias»** ya no te dice que solo es para marcas.
- La primera vez, Gemini prepara **30 temas reales de tu nicho**, con un gancho y formatos
  variados. Se guardan, así que las siguientes veces no gasta Gemini.
- JARVIS te enseña 5 temas cada vez, con los botones **🎬** para empezar el vídeo, y los
  que ya hiciste **no vuelven a salir** («Llevas 3 de 30»).
- Si cambias el nicho del canal, prepara un banco nuevo para el nicho nuevo.
- El canal de marcas sigue con su banco de 80 historias de siempre.

## 2026-10-08 — Versión 0.71: JARVIS revisa tu ordenador cada lunes

- Cada **lunes**, a la hora de tu piloto automático (las 9 si no la cambiaste), JARVIS
  pasa solo **«Revisar mi ordenador»**: voz gratuita, montaje de vídeo, internet, espacio
  en disco, claves y pasos detenidos.
- **Solo te escribe por Telegram si algo falla** o conviene mirarlo, con qué hacer para
  arreglarlo. Si todo va bien, no te molesta.
- Si el lunes el ordenador estaba apagado, lo revisa el **primer día que lo abras** esa
  semana.
- En el mensaje hay un botón **«🩺 Revisar otra vez»** para comprobar si ya quedó bien.

## 2026-10-07 — Versión 0.70.1: revisión de salud

Revisión de los cambios de la semana con los revisores automáticos. Se arreglaron 3 fallos:

- **«Leer comentarios»** decía «Aún no hay comentarios en tus vídeos» cuando en realidad
  YouTube rechazaba tu clave (por ejemplo, si se acaba la cuota del día). Ahora te dice
  la verdad: que la clave no funciona o que se acabó la cuota, y qué hacer.
- La **voz gratuita (Piper)**: si la primera vez tardaba mucho en arrancar (el antivirus
  la revisa), se quedaba marcada como rota hasta cerrar el programa. Ahora te dice que
  tardó y lo vuelve a intentar la próxima vez.
- **Telegram**: el código de 6 cifras para vincular JARVIS se cambia solo tras 5 intentos
  equivocados, para que nadie pueda adivinarlo probando números. El código bueno
  siempre lo ves en la página **JARVIS**.

## 2026-10-07 — Versión 0.70: respuestas a comentarios listas para pegar

- En **Rendimiento → «Lo que pide tu audiencia»**, al pulsar **«Leer comentarios»**
  aparece un apartado nuevo: **«✍️ Comentarios por responder»**.
- Salen los **5 comentarios con más «me gusta»** que aún no tienen respuesta, cada uno con
  un **borrador** de respuesta corto y cercano escrito por la IA.
- Pulsa **«Copiar»**, luego **«Abrir en YouTube»** (te lleva justo a ese comentario) y
  pega la respuesta. Revísala antes: el programa **no publica nada** solo.
- Responder pronto a los comentarios ayuda a que YouTube enseñe más tu vídeo.

## 2026-10-06 — Versión 0.69.1: el informe de audiencia siempre a la vista

- La tarjeta «Lo que pide tu audiencia» enseña el último informe aunque la clave de
  YouTube se haya quitado después.

## 2026-10-06 — Versión 0.69: revisar mi ordenador

- En **Configuración** hay un botón nuevo, **«🩺 Revisar mi ordenador»**. En unos segundos
  comprueba la voz gratuita, el montaje de vídeo, internet, las claves de Gemini y
  YouTube, el espacio libre en disco, si el programa está en OneDrive y si hay pasos
  detenidos. Te dice qué falla y **qué hacer**, en palabras sencillas.
- También puedes decirle a JARVIS **«revisa mi ordenador»**.

## 2026-10-06 — Versión 0.68.1: no más bucles de «abro y se cierra»

- Si el programa se cierra **3 veces** a mitad del mismo paso de un vídeo, ya no lo
  retoma solo al abrirlo (podría ser ese paso lo que lo cierra). Lo deja en rojo con una
  explicación y el botón «Reintentar», y el resto del programa funciona con normalidad.

## 2026-10-06 — Versión 0.68: banco de 80 historias

- El **banco de historias** de JARVIS pasa de 37 a **80 historias reales**, sobre todo de
  **España** (Bankia, Mercadona, Gowex, Terra, Telepizza, Marsans…) y **Latinoamérica**
  (Cemex, Juan Valdez, Interbolsa, Postobón, Oxxo, Quilmes, Falabella, Pollo Campero…).
- Al pedir «banco de historias», JARVIS te dice **cuántas llevas hechas** («Llevas 5 de
  80»), y las que ya hiciste no vuelven a salir.

## 2026-10-06 — Versión 0.67: lo que pide tu audiencia

- En **Rendimiento** hay una tarjeta nueva, **«💬 Lo que pide tu audiencia»**: pulsa
  «Leer comentarios» y JARVIS lee los comentarios de tus últimos 10 vídeos (con la clave
  gratuita de YouTube) y te dice qué **temas te piden** (con botón «Hacer este vídeo»),
  qué **preguntas se repiten**, qué gusta, qué molesta y un texto listo para el
  **comentario fijado** del próximo vídeo.
- Pregúntale a JARVIS **«¿qué pide mi audiencia?»** o **«lee mis comentarios»** y te lo
  cuenta, con botones para empezar esos vídeos.
- Cuando le pides **ideas**, JARVIS da prioridad a lo que pide tu audiencia.

## 2026-10-06 — Versión 0.66.2: la voz gratuita ya no puede apagar el programa

- En algunos Windows (rutas con tilde, como «Simón», o dentro de OneDrive), la
  pronunciación de **Piper** (espeak-ng) no encontraba sus archivos y **cerraba el
  programa entero**. Si había un vídeo a medias en el paso de voz, se cerraba nada más
  abrirlo («Error processing file … phontab»).
- Ahora esos archivos se copian a una carpeta con ruta sencilla, y Piper se prueba
  antes en un proceso aparte: si aun así fallara, solo falla la voz con un mensaje claro
  y el programa sigue encendido.

## 2026-10-06 — Versión 0.66.1: el navegador espera a que el programa esté listo

- Antes, Iniciar abría el navegador a los 2 segundos aunque el programa aún no hubiera
  terminado de arrancar (pasa en ordenadores lentos o la primera vez tras actualizar), y
  salía **«No se puede acceder a este sitio web»**. Ahora el navegador se abre solo
  cuando el programa ya responde.

## 2026-10-06 — Versión 0.66: abrir y actualizar aunque JARVIS ya esté encendido

- Si tienes **JARVIS al encender**, el programa queda encendido en una ventana minimizada.
  Antes, **Iniciar** decía «ya hay otro abierto» y **Actualizar** «el programa está
  abierto», y no dejaban hacer nada.
- Ahora **Iniciar** simplemente te lo abre en el navegador, y **Actualizar** lo apaga solo
  (solo si es Faceless Studio), actualiza y te avisa. Lo que estuviera a medias se retoma
  al volver a encenderlo.

## 2026-10-06 — Versión 0.65: ¿se lee la miniatura en pequeño?

- En **Miniatura**, cada una dice **«📱 Se lee bien en pequeño»** o te avisa si la letra
  queda demasiado pequeña cuando YouTube la enseña reducida (búsquedas y vídeos
  sugeridos) o si tiene demasiadas palabras (mejor 2–4).

## 2026-10-06 — Versión 0.64: aviso cuando algo se dispara en tus referencias

- Si tienes Telegram conectado, JARVIS revisa tus **canales de referencia** cada 6 horas y
  te avisa cuando un vídeo de las últimas 2 semanas va **más de ×3 su media**, con botones
  para hacer tu versión. Cada vídeo se avisa una sola vez.

## 2026-10-06 — Versión 0.63: referencias en la pantalla de JARVIS

- En la **pantalla de JARVIS**, la cinta de abajo enseña también los vídeos que destacan
  en tus canales de referencia (🔥).
- La bienvenida para gente nueva incluye los pasos de **referencias** y **Semana**.

## 2026-10-06 — Versión 0.62: JARVIS conoce tus referencias

- Pregúntale **«¿qué funciona en mis referencias?»** y te dice los vídeos que más
  destacan en tus canales de referencia, con botones para hacer tu versión.
- Cuando le pides **«ideas»**, también se inspira en esos temas que están funcionando (sin
  copiarlos y sin hacerte esperar).

## 2026-10-06 — Versión 0.61: canales de referencia

- Nueva página **«🔭 Canales de referencia»** (botón en Rendimiento): pones el @ de 3–8
  canales de tu nicho y ves sus últimos vídeos con las **visitas por día** frente a la
  media de ese canal.
- 🔥 marca los que van **el doble o más** de lo normal: temas con interés demostrado. Con
  **«Hacer mi versión»** empiezas un vídeo sobre ese tema (con tu investigación y tu
  enfoque, nunca copiando).
- Gratis y sin clave (lee sus últimos 15 vídeos); con la clave de YouTube, datos exactos.

## 2026-10-06 — Versión 0.60: todo para subir, en un archivo

- En **Publicación**, el botón **«📦 Descargar todo para subir»** baja un .zip con: el
  vídeo, los subtítulos, la miniatura elegida, un texto con título, descripción,
  etiquetas y comentario fijado listos para pegar, los créditos y los Shorts con sus
  portadas y textos. Incluye un «LEEME» con los pasos para subirlo.

## 2026-10-06 — Versión 0.59: portada más útil y detalles de diseño

- **Empezar un vídeo en un paso**: en la portada, la caja «✨ ¿Sobre qué hacemos el próximo
  vídeo?»: escribes la idea, pulsas «Empezar» y se pone a investigar con tu canal y
  duración de siempre (y deduce el formato: «top 10 de…» sale como lista).
- **Indicador arriba** en todas las páginas con lo que se está fabricando («⏳ Guion 45 %»):
  pulsando vas al vídeo.
- La página de cada vídeo enseña arriba el **vídeo montado**, su miniatura y la nota.
- **Buscador** de vídeos en la portada (aparece cuando tienes más de 6).
- Los **Shorts** se ven con forma de móvil; los reproductores de audio y vídeo, en oscuro;
  la página de **JARVIS** ordena sus ajustes en dos columnas.

## 2026-10-06 — Versión 0.58: guion más humano

- En **Guion**, debajo del mapa, un aviso **«🗣️ Guion más humano»** te dice cuántos
  párrafos tienen frases que suenan raras al narrarlas.
- Esos párrafos salen con una **raya amarilla** y el motivo: frase demasiado larga (más
  de 30 palabras), una palabra repetida 3 veces o relleno («básicamente», «cabe destacar»…).
- El botón **«Hacerlo más humano»** pide a la IA que cambie **solo esas frases** y deje el
  resto del párrafo igual, con los mismos datos.
- El **Control de calidad** avisa si más del 15 % de los párrafos tienen estos fallos.

## 2026-10-06 — Versión 0.57: Configuración más clara

- Arriba de **Configuración** hay un **panel con cada servicio** (Gemini, imágenes,
  ElevenLabs, Telegram, YouTube…): verde si está conectado, rojo si hace falta. Pulsando
  uno vas directo a sus instrucciones.
- En **Estrategia**, cada título muestra **cuántas letras tiene** (amarillo si pasa de 60:
  en el móvil se corta).
- La pantalla de entrada tiene el **logo** y una frase de bienvenida.

## 2026-10-06 — Versión 0.56: tu semana en un calendario

- Nueva página **«📅 Semana»** (en el menú de arriba): los próximos 7 días con lo que toca
  cada uno: 🎬 el vídeo largo (o qué te falta para tenerlo), 📱 los Shorts y 📚 los 30
  minutos para aprender. Hoy aparece marcado.
- Desde ahí cambias el **día y la hora** de tu vídeo largo semanal.

## 2026-10-06 — Versión 0.55: así se verá en YouTube

- En **Miniatura** hay una vista **«👀 Así se verá en YouTube»**: tus 3 miniaturas con el
  título, la duración y el nombre de tu canal, igual que en la portada de YouTube.
- Con el selector de **título** cambias el título de las tres a la vez para ver qué
  combinación llama más. El título se corta a dos líneas como en el móvil.
- El campo «En rojo» ahora se llama «Destacada», porque usa el color de tu canal.

## 2026-10-06 — Versión 0.54: lista para subir con casillas

- En **Publicación**, la «Lista para subir el vídeo» tiene **casillas**: vas marcando cada
  paso (subir el MP4, título, miniatura, subtítulos…) y arriba ves «3 de 7».
- Se recuerda en tu ordenador aunque cierres la página.

## 2026-10-06 — Versión 0.53: mapa del guion

- Arriba del guion hay un **mapa de colores** con cada parte (gancho, desarrollo, clímax,
  final…) y el **minuto** en que empieza. Pulsando una parte vas directo a ella.
- Si hay un tramo largo **sin preguntas ni adelantos**, se marca a rayas amarillas en el
  mapa y te dice el minuto para que lo arregles.

## 2026-10-06 — Versión 0.52: detalles profesionales

- **Icono propio** en la pestaña del navegador y **títulos de pestaña** con el nombre del
  vídeo o de la página (así distingues varias pestañas abiertas).
- Al pulsar un botón, **muestra que está trabajando** y no se puede pulsar dos veces sin
  querer.
- En la página de cada vídeo, si las miniaturas están hechas pero no elegidas, el
  «Siguiente paso» te pide **elegir la miniatura** (antes decía «Todo listo»).

## 2026-10-06 — Versión 0.51: más detalles de diseño

- La **nota del Control de calidad** se ve en un anillo de color (verde, amarillo o rojo)
  en vez de un número que se montaba sobre el texto.
- Botones de «elegir archivo», casillas y espacios más cuidados.
- En Rendimiento, si no se lee el canal, te lleva a **Mi perfil** para escribir tu @canal.

## 2026-10-06 — Versión 0.50: más ritmo (ideas de los vídeos de esta noche)

- **Voz sin silencios de sobra**: cada párrafo grabado pierde el silencio del principio y
  del final, y las pausas de más de medio segundo se acortan. Las guías de retención lo
  recomiendan: el vídeo gana ritmo (suele quedar un 5–10 % más corto).
- **Nuevo control de calidad, «re-enganches»**: avisa si hay un tramo de más de 2 minutos
  del guion sin una pregunta o un adelanto («lo peor estaba por llegar…»), y te dice el
  minuto exacto para que lo arregles con «Otra forma».
- 5 vídeos nuevos para aprender en `docs/videos-para-aprender.md` (guion documental, cómo
  funciona un canal documental viral y dos en español).

## 2026-10-06 — Versión 0.49: diseño nuevo

- **Aspecto más cuidado**: tipografías del canal (Montserrat y Bebas), tarjetas con relieve,
  botones con brillo y movimientos suaves. El menú de arriba se queda fijo y marca la
  página en la que estás.
- **Portada con resumen**: vídeos en marcha, listos para subir, publicados y la nota media
  de calidad, más «👉 Lo siguiente» con lo que toca en cada vídeo.
- Las tarjetas de los vídeos enseñan **su miniatura**.
- En cada vídeo, la **producción es una línea de pasos** con círculos (verde = hecho,
  azul = trabajando, rojo = falló).
- **En el móvil ya no se sale nada de la pantalla**: el menú se desliza de lado.

## 2026-10-06 — Versión 0.48: cuánto gasta cada vídeo

- Tercera idea de «AS Video Studio»: en la página de cada vídeo hay un apartado
  **«💸 Consumo de este vídeo»** con las llamadas a Gemini, el texto procesado y los
  créditos de ElevenLabs que gastó, por etapa.
- Abajo ves el **total del mes**: útil para saber si te alcanza el plan gratis y, cuando
  pagues ElevenLabs, cuánto te cuesta cada vídeo.
- Se empieza a contar desde esta versión.

## 2026-10-06 — Versión 0.47: cifras animadas

- Otra idea de «AS Video Studio»: cuando la voz dice un dato importante («50 millones»,
  «el 80 %», «1975»), **aparece grande en pantalla** justo en ese momento, con el color
  del canal, y desaparece a los 2 segundos.
- Lo detecta solo, sin gastar IA. Da más ritmo y ayuda a que la gente no se vaya.
- Se puede quitar en **Vídeo → Acabado → «Cifras animadas»**.

## 2026-10-06 — Versión 0.46: el vídeo se rehace mucho más rápido

- Idea sacada de «AS Video Studio»: al volver a montar el vídeo, **solo se rehacen las
  escenas que cambiaron**. Si tocas un párrafo, una imagen o un texto en pantalla, el resto
  sale de la memoria y el montaje tarda mucho menos.
- La voz y las imágenes ya funcionaban así; ahora también el montaje (y los Shorts).
- El movimiento de cámara de cada escena ya no cambia al tocar otra escena.

## 2026-10-06 — Versión 0.45.1: pregúntale a JARVIS qué busca la gente

- Dile a JARVIS **«¿qué busca la gente sobre Nokia?»** o **«¿tiene demanda el caso Enron?»**
  y te dice la demanda en YouTube y las búsquedas reales, para usarlas en títulos y
  etiquetas.

## 2026-10-06 — Versión 0.45: publicar con las palabras que busca la gente

- En **Publicación** hay una tarjeta nueva, **«🔎 Lo que busca la gente»**: la búsqueda
  principal del vídeo, cuánta demanda tiene en YouTube y qué escribe la gente.
- Esas búsquedas reales van **primero en las etiquetas**.
- Si el título no usa esas palabras, te avisa para que las metas sin perder la intriga.
- Arreglado: la **atribución de la música** (si la licencia la pide) ahora también va en la
  descripción del vídeo.

## 2026-10-06 — Versión 0.44.2: detalle en la página del guion

- En **Guion** se ve el formato del vídeo (por ejemplo «Top / lista») y el nombre de la
  estructura usada, también cuando viene de la ficha del nicho.

## 2026-10-06 — Versión 0.44.1: «ideas» sigue siendo rápido

- La comprobación de lo que se busca en YouTube se hace **a la vez para todas las ideas**
  (antes, una detrás de otra) y no espera más de 3 segundos.
- Las noticias del nicho para inspirar ideas se toman de lo ya descargado: JARVIS no se
  queda esperando a internet.

## 2026-10-06 — Versión 0.44: ideas que la gente busca

- Cuando le pides **«ideas»** a JARVIS, ahora comprueba qué se busca de verdad en YouTube
  (lo que aparece al escribir en el buscador) y te pone **primero las que tienen demanda**.
- Cada idea dice 🔥 demanda alta, 📈 media o 🌱 baja, y **qué escribe la gente**, para que
  uses esas palabras en el título.
- Las ideas también se inspiran en las **noticias de tu nicho** de esta semana y en tus
  vídeos que mejor funcionaron.

## 2026-10-06 — Versión 0.43: música con licencia apuntada

- En **Vídeo → Biblioteca de música**, cada canción tiene «¿De dónde salió?»: Biblioteca
  de audio de YouTube, Pixabay, comprada, Creative Commons con atribución, hecha por ti…
- Con el origen apuntado, el **Control de calidad** la da por buena (ya no avisa siempre).
- Si la licencia pide citar al autor, escribes la atribución una vez y se añade sola a
  los **créditos** del vídeo (para pegarlos en la descripción).
- Al lado de cada canción ves si está ✅ con licencia, ⚠️ falta atribución o ❓ sin apuntar.

## 2026-10-06 — Versión 0.42: la pantalla de JARVIS muestra tu semana

- Nuevo panel **«ESTA SEMANA»** en la pantalla de JARVIS: qué vídeo subir (o terminar) y
  cuándo, los Shorts de los próximos días y las barras de **suscriptores** y **horas
  vistas** hacia la monetización.
- Si vas a buen ritmo, te dice la **fecha estimada** para llegar a 1.000 suscriptores, y
  un consejo para ir más rápido.
- Se actualiza solo cada 2 minutos.

## 2026-10-06 — Versión 0.41: el guion aprende de la retención

- En **📈 Rendimiento**, cada vídeo tiene dos casillas nuevas: «30 s» (cuánta gente sigue
  viendo a los 30 segundos) y «Mitad» (cuánta sigue a la mitad). Salen en YouTube Studio →
  el vídeo → Estadísticas → Interacción, pasando el ratón por la gráfica.
- El programa te dice dónde se va la gente: «el gancho pierde gente», «el desarrollo se
  hace largo» o «falta ritmo».
- **El próximo guion lo refuerza solo**: gancho más directo, giros cada 60–90 segundos o
  más ritmo, según lo que digan tus datos. Lo ves en la tarjeta «📉 Retención».
- El análisis de JARVIS también usa estos datos.

## 2026-10-06 — Versión 0.40: formatos de vídeo y color de cada canal

- **Formato del vídeo** al crearlo: «Top / lista» (cuenta atrás con el número uno al
  final), «Explicación» (una pregunta explicada paso a paso, con un mito desmontado),
  «Relato» (contado como una historia con escenas y suspense) o automático (el documental
  de siempre, con las estructuras de la ficha). La estrategia y el guion se adaptan.
- JARVIS lo entiende solo: «hazme un vídeo top 10 de…» o «explica por qué…».
- **Color del canal** en Canales (rojo, amarillo, naranja, verde, cian, azul, morado o
  rosa): se usa en subtítulos, textos en pantalla, gráficos, miniaturas y Shorts. Tu
  canal sigue en rojo.

## 2026-10-06 — Versión 0.39: sirve para cualquier nicho

- **Ficha del nicho**: en 🧭 Canales cada canal tiene su ficha: cómo son sus vídeos, para
  quién, el tono, 4–5 estructuras de guion, su sección final fija (en tu canal sigue
  siendo «La lección de la marca»), consejos de títulos y miniaturas y los riesgos del
  nicho con YouTube. La crea la IA con un botón (o sola con el primer vídeo).
- **Guion, estrategia y miniaturas** usan la ficha del canal: un canal de finanzas o de
  misterios ya no recibe consejos de marcas.
- **Ideas, radar de noticias y dato curioso** salen del nicho de cada canal.
- Se puede **cambiar el nicho** de un canal en Canales.
- **Tu canal no cambia**: al ser de marcas usa la ficha de siempre y el banco de historias.

## 2026-10-06 — Versión 0.38: para compartir con otras personas

- **Perfil**: nombre, canal, de qué son los vídeos y país. Los guiones, JARVIS, «Aprender»
  y las cifras del canal lo usan en vez de llevar tu nombre escrito a fuego.
- **Tú no tienes que hacer nada**: como ya tenías proyectos, tu perfil («Anatomía De Una
  Marca», Colombia) se rellena solo. Puedes verlo en Configuración → 👤 Mi perfil.
- **Para otra persona**: instala con la misma línea que tú. Al crear su cuenta le salen la
  bienvenida y sus primeros pasos (Gemini, canal, primer vídeo). Tiene su propia base de
  datos y sus propias claves: no ve nada tuyo ni tú lo suyo.
- La línea para instalar se copia con un botón en «Mi perfil y compartir».
- Las noticias y el radar de marcas salen del país de cada persona.

## 2026-10-06 — Versión 0.37: investigar en YouTube

- **Investigar un tema viendo vídeos**: en 🎓 Aprender escribes un tema («monetizar un
  canal faceless») o le dices a JARVIS «investiga en YouTube canales faceless». El
  programa busca los 3 vídeos más útiles (de 4 a 20 minutos), Gemini los ve uno por uno
  y te junta lo que repiten los que saben: consejos, qué hacer en tu canal, lo que no
  conviene e ideas de vídeo.
- Lo hace **por detrás** (tarda unos minutos) y JARVIS te avisa por Telegram al terminar.
- Cada vídeo visto queda también como lección: puedes marcarla para tus guiones.
- Busca con la clave de YouTube si la tienes; si no, en la búsqueda pública de YouTube
  o en Google. Comprueba que cada vídeo existe antes de verlo.

## 2026-10-06 — Versión 0.36: Shorts que llevan al documental

- **Cartel final** en cada Short: los últimos 3 segundos sale «LA HISTORIA COMPLETA, EN
  EL CANAL» en grande, para que quien lo ve vaya al vídeo largo.
- **Mejores fragmentos**: la IA elige trozos que empiezan fuerte en los 2 primeros
  segundos y terminan con la intriga abierta (sin contar el final).
- **Enlace del vídeo largo**: en la página de Shorts pegas el enlace del documental y se
  añade a la descripción de todos los Shorts. También te deja listo el comentario para fijar.
- **Vídeo relacionado**: la guía de subida explica cómo poner el documental como «Vídeo
  relacionado» en YouTube Studio (sale un botón debajo del Short).
- El Control de calidad avisa si a los Shorts les falta el enlace.

## 2026-10-03 — Versión 0.35: lista de la compra y cuentas

- **Lista de la compra por voz**: «añade leche y azúcar a la lista de la compra», «¿qué
  hay en la lista?», «ya compré la leche», «borra la lista de la compra».
- **Cuentas al instante** (sin esperar a Google): «¿cuánto es 25 por 4?», «el 15 por
  ciento de 80.000», «calcula 3500 entre 7». Entiende números escritos como en Colombia.
- Conversiones, traducciones y recetas: pregúntaselas normal y las busca.

## 2026-10-03 — Versión 0.34: JARVIS controla el ordenador

- **Carpetas**: «abre descargas», «abre documentos», «abre la carpeta de datos»…
- **Programas**: «abre la calculadora», «abre el bloc de notas», Word, Excel, Spotify…
- **Volumen y música**: «sube/baja el volumen», «silencia», «pausa», «siguiente
  canción», «canción anterior».
- **«Bloquea el ordenador»** (no apaga ni borra nada: es a propósito).
- Funciona también por Telegram: lo hace en el ordenador donde está el programa.

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
