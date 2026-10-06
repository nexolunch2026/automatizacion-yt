"""Banco de ideas para canales de documentales sobre marcas.

Historias reales y comprobables, con formatos distintos (para que el canal no parezca
hecho en serie) y de varias regiones (España, Latinoamérica y el resto del mundo). JARVIS
las ofrece sin gastar IA ni internet, y sirven de reserva si Gemini no responde.

Cada idea: tema, formato (una de las estructuras del guion), región y gancho. Los datos
del gancho son conocidos; aun así, la etapa de investigación los comprueba con fuentes.
"""

import unicodedata

FORMAT_LABELS = {
    "auge_caida": "Ascenso y caída",
    "errores": "Los errores clave",
    "rivalidad": "Rivalidad",
    "investigacion": "Investigación / escándalo",
    "cronologia": "Cronológica",
}

IDEAS: list[dict] = [
    # ---------------------------------------------------------------- resto del mundo
    {
        "topic": "Blockbuster: la cadena que pudo comprar Netflix",
        "format": "errores",
        "region": "Mundo",
        "hook": "En el año 2000 pudo comprar Netflix por unos 50 millones de dólares. Dijo que no.",
    },
    {
        "topic": "Kodak: la empresa que inventó la cámara digital y la escondió",
        "format": "errores",
        "region": "Mundo",
        "hook": "Un ingeniero de Kodak creó la primera cámara digital en 1975.",
    },
    {
        "topic": "Nokia: de reina de los móviles a desaparecer",
        "format": "auge_caida",
        "region": "Mundo",
        "hook": "Vendía uno de cada tres móviles del planeta y lo perdió en pocos años.",
    },
    {
        "topic": "BlackBerry: el móvil de los presidentes que no vio venir la pantalla táctil",
        "format": "auge_caida",
        "region": "Mundo",
        "hook": "Era tan adictivo que lo llamaban «CrackBerry».",
    },
    {
        "topic": "Toys «R» Us: la juguetería gigante que hundió una deuda",
        "format": "investigacion",
        "region": "Mundo",
        "hook": "No la mató internet: la mató la deuda con la que la compraron.",
    },
    {
        "topic": "MySpace: la red social más visitada que Facebook borró del mapa",
        "format": "rivalidad",
        "region": "Mundo",
        "hook": "Fue la web más visitada de Estados Unidos, por delante de Google.",
    },
    {
        "topic": "Yahoo: la empresa que dijo no a Google y a Microsoft",
        "format": "errores",
        "region": "Mundo",
        "hook": "En 2008 rechazó una oferta de Microsoft de más de 44.000 millones de dólares.",
    },
    {
        "topic": "Quibi: 1.750 millones de dólares para cerrar en seis meses",
        "format": "errores",
        "region": "Mundo",
        "hook": "Reunió a las grandes estrellas de Hollywood y cerró a los seis meses de nacer.",
    },
    {
        "topic": "Enron: el fraude que tumbó a una de las mayores empresas de EE. UU.",
        "format": "investigacion",
        "region": "Mundo",
        "hook": "La revista Fortune la eligió la empresa más innovadora seis años seguidos.",
    },
    {
        "topic": "Theranos: la startup que prometía análisis con una gota de sangre",
        "format": "investigacion",
        "region": "Mundo",
        "hook": "Llegó a valer miles de millones con una máquina que no funcionaba.",
    },
    {
        "topic": "WeWork: de valer 47.000 millones a la bancarrota",
        "format": "auge_caida",
        "region": "Mundo",
        "hook": "Alquilaba oficinas, pero se vendía como una empresa de tecnología.",
    },
    {
        "topic": "FTX: el imperio cripto que se evaporó en una semana",
        "format": "investigacion",
        "region": "Mundo",
        "hook": "En noviembre de 2022, una semana bastó para que todo se viniera abajo.",
    },
    {
        "topic": "Volkswagen y el Dieselgate: el software que engañaba a los controles",
        "format": "investigacion",
        "region": "Mundo",
        "hook": "Los coches sabían cuándo los estaban examinando.",
    },
    {
        "topic": "Adidas contra Puma: dos hermanos que dividieron un pueblo",
        "format": "rivalidad",
        "region": "Mundo",
        "hook": "En Herzogenaurach, durante décadas, cada familia era de Adidas o de Puma.",
    },
    {
        "topic": "Coca-Cola contra Pepsi y el desastre de la «New Coke»",
        "format": "rivalidad",
        "region": "Mundo",
        "hook": "En 1985 Coca-Cola cambió su fórmula. Tuvo que dar marcha atrás en 79 días.",
    },
    {
        "topic": "Nintendo contra Sega: la guerra de las consolas",
        "format": "rivalidad",
        "region": "Mundo",
        "hook": "Sega llegó a vender más que Nintendo en Estados Unidos. Y luego lo perdió todo.",
    },
    {
        "topic": "Apple en 1997: a semanas de la quiebra",
        "format": "cronologia",
        "region": "Mundo",
        "hook": "El rescate de Apple llegó de su mayor rival: Microsoft.",
    },
    {
        "topic": "LEGO: cómo la empresa de juguetes casi quiebra y se reinventó",
        "format": "errores",
        "region": "Mundo",
        "hook": "A principios de los 2000, LEGO perdía dinero con casi todo lo que hacía.",
    },
    {
        "topic": "Marvel: de la bancarrota al imperio del cine",
        "format": "cronologia",
        "region": "Mundo",
        "hook": "En 1996 Marvel estaba en quiebra y vendía los derechos de sus héroes.",
    },
    {
        "topic": "Pan Am: la aerolínea más famosa del mundo que dejó de volar",
        "format": "auge_caida",
        "region": "Mundo",
        "hook": "Era tan icónica que salía en las películas de ciencia ficción.",
    },
    # ---------------------------------------------------------------- España
    {
        "topic": "Pescanova: el fraude contable de la gigante del pescado",
        "format": "investigacion",
        "region": "España",
        "hook": "Una de las mayores pesqueras del mundo escondía un agujero enorme en sus cuentas.",
    },
    {
        "topic": "Rumasa: la expropiación del imperio de Ruiz-Mateos",
        "format": "investigacion",
        "region": "España",
        "hook": "En 1983 el Gobierno expropió un grupo de cientos de empresas de un día para otro.",
    },
    {
        "topic": "Spanair: la aerolínea que cerró de un día para otro",
        "format": "auge_caida",
        "region": "España",
        "hook": "En enero de 2012 miles de pasajeros se quedaron en tierra sin aviso.",
    },
    {
        "topic": "Fórum Filatélico y Afinsa: la estafa de los sellos",
        "format": "investigacion",
        "region": "España",
        "hook": "Cientos de miles de personas invirtieron sus ahorros en sellos.",
    },
    {
        "topic": "Zara: de una tienda en A Coruña al mayor grupo de moda del mundo",
        "format": "cronologia",
        "region": "España",
        "hook": "Su secreto no es la ropa: es la velocidad.",
    },
    {
        "topic": "Chupa Chups: el caramelo con un logo de Dalí",
        "format": "cronologia",
        "region": "España",
        "hook": "El logo de uno de los caramelos más famosos del mundo lo dibujó Salvador Dalí.",
    },
    # ---------------------------------------------------------------- Latinoamérica
    {
        "topic": "Mexicana de Aviación: la aerolínea histórica que dejó de volar",
        "format": "auge_caida",
        "region": "Latinoamérica",
        "hook": "En 2010 una de las aerolíneas más antiguas del continente dejó de volar.",
    },
    {
        "topic": "La Polar: el escándalo que sacudió al comercio en Chile",
        "format": "investigacion",
        "region": "Latinoamérica",
        "hook": "Renegociaba las deudas de sus clientes sin pedirles permiso.",
    },
    {
        "topic": "La colusión del papel higiénico en Chile",
        "format": "investigacion",
        "region": "Latinoamérica",
        "hook": "Durante años, dos empresas pactaron el precio de algo que usas a diario.",
    },
    {
        "topic": "Americanas: el agujero contable que asombró a Brasil",
        "format": "investigacion",
        "region": "Latinoamérica",
        "hook": "En 2023 una de las mayores cadenas de Brasil reveló un agujero gigante.",
    },
    {
        "topic": "Odebrecht: la constructora que exportó sobornos a un continente",
        "format": "investigacion",
        "region": "Latinoamérica",
        "hook": "Tenía un departamento entero dedicado a pagar sobornos.",
    },
    {
        "topic": "Eike Batista: el hombre más rico de Brasil que lo perdió todo",
        "format": "auge_caida",
        "region": "Latinoamérica",
        "hook": "Quería ser el hombre más rico del mundo. Acabó en la ruina.",
    },
    {
        "topic": "Inca Kola contra Coca-Cola: la bebida que Coca-Cola no pudo vencer en Perú",
        "format": "rivalidad",
        "region": "Latinoamérica",
        "hook": "Es uno de los pocos países donde Coca-Cola no logró ser la número uno.",
    },
    {
        "topic": "Bimbo: de una panadería en México a la mayor del mundo",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Empezó en 1945 en Ciudad de México y hoy está en decenas de países.",
    },
    {
        "topic": "Mercado Libre: el proyecto de un estudiante que conquistó Latinoamérica",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Nació como un plan de negocios en la universidad, en plena burbuja de internet.",
    },
    {
        "topic": "Avianca: la quiebra y el rescate de una aerolínea centenaria",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Una de las aerolíneas más antiguas del mundo se declaró en quiebra en 2020.",
    },
    # ---------------------------------------------------------------- ampliación (0.68)
    {
        "topic": "Bankia: la salida a bolsa que acabó en rescate",
        "format": "investigacion",
        "region": "España",
        "hook": "Salió a bolsa en 2011 y al año siguiente pidió un rescate de 19.000 millones.",
    },
    {
        "topic": "Mercadona: el supermercado que cambió la forma de comprar en España",
        "format": "cronologia",
        "region": "España",
        "hook": "Empezó como un negocio familiar de carnicerías en Valencia.",
    },
    {
        "topic": "Fagor Electrodomésticos: la caída de la joya de las cooperativas",
        "format": "auge_caida",
        "region": "España",
        "hook": "En 2013 quebró la gran marca de Mondragón, con miles de empleos en el aire.",
    },
    {
        "topic": "Telepizza: de una pizzería en Madrid a gigante del reparto",
        "format": "cronologia",
        "region": "España",
        "hook": "La fundó en 1987 un empresario cubano-estadounidense, Leopoldo Fernández Pujals.",
    },
    {
        "topic": "Panrico y los Donuts: la marca que casi se queda sin dueño",
        "format": "auge_caida",
        "region": "España",
        "hook": "Los Donuts eran tan populares que mucha gente no sabía que era una marca.",
    },
    {
        "topic": "Abengoa: la gigante de las renovables al borde de la mayor quiebra de España",
        "format": "auge_caida",
        "region": "España",
        "hook": "En 2015 entró en preconcurso con una deuda cercana a los 9.000 millones de euros.",
    },
    {
        "topic": "Gowex: la empresa del wifi gratis que era un fraude",
        "format": "investigacion",
        "region": "España",
        "hook": "En 2014 un informe de un fondo bajista la desmontó en días y su fundador confesó.",
    },
    {
        "topic": "Seat: el coche que motorizó España y acabó en manos de Volkswagen",
        "format": "cronologia",
        "region": "España",
        "hook": "El Seat 600 llenó las carreteras españolas en los años sesenta.",
    },
    {
        "topic": "Mango contra Zara: dos formas de vestir a medio mundo",
        "format": "rivalidad",
        "region": "España",
        "hook": "Isak Andic abrió su primera tienda en el Paseo de Gracia de Barcelona en 1984.",
    },
    {
        "topic": "Cola Cao contra Nesquik: la guerra del desayuno en España",
        "format": "rivalidad",
        "region": "España",
        "hook": "Nació en Barcelona en los años cuarenta y aguantó a las multinacionales.",
    },
    {
        "topic": "Terra: la burbuja puntocom de Telefónica",
        "format": "errores",
        "region": "España",
        "hook": "Salió a bolsa a menos de 12 euros por acción y en pocos meses superó los 100.",
    },
    {
        "topic": "El Corte Inglés: de sastrería a gigante de los grandes almacenes",
        "format": "cronologia",
        "region": "España",
        "hook": "Empezó como una pequeña sastrería en el centro de Madrid.",
    },
    {
        "topic": "Martinsa-Fadesa: la quiebra que reventó la burbuja del ladrillo",
        "format": "investigacion",
        "region": "España",
        "hook": "En 2008 presentó concurso con una deuda de unos 7.000 millones de euros.",
    },
    {
        "topic": "Viajes Marsans: la agencia que dejó a miles de viajeros en tierra",
        "format": "auge_caida",
        "region": "España",
        "hook": "En 2010 miles de clientes se quedaron sin el viaje que ya habían pagado.",
    },
    {
        "topic": "Freixenet contra Codorníu: la guerra del cava",
        "format": "rivalidad",
        "region": "España",
        "hook": "Dos familias catalanas se disputaron durante décadas las burbujas de las fiestas.",
    },
    {
        "topic": "Banco Latino: el banco que desató la crisis financiera de Venezuela",
        "format": "investigacion",
        "region": "Latinoamérica",
        "hook": "En 1994 cayó el segundo banco del país y arrastró a buena parte del sistema.",
    },
    {
        "topic": "Cemex: la cementera mexicana que conquistó el mundo y casi quiebra",
        "format": "auge_caida",
        "region": "Latinoamérica",
        "hook": "Hizo una compra gigantesca en Australia justo antes de la crisis de 2008.",
    },
    {
        "topic": "Telmex: la compra que hizo a Carlos Slim el hombre más rico del mundo",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "La privatización de Telmex en 1990 fue el inicio de su gran fortuna.",
    },
    {
        "topic": "Embraer: la empresa estatal brasileña que aprendió a fabricar aviones",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Nació en 1969 como empresa del Estado brasileño.",
    },
    {
        "topic": "Natura: la marca brasileña de cosméticos que compró Avon",
        "format": "rivalidad",
        "region": "Latinoamérica",
        "hook": "En 2020 una empresa brasileña se quedó con la mítica Avon.",
    },
    {
        "topic": "Rappi: el unicornio colombiano del reparto",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Nació en 2015 en Bogotá y en pocos años valía miles de millones de dólares.",
    },
    {
        "topic": "Juan Valdez: el personaje inventado que vendió el café de Colombia",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Juan Valdez no existe: lo crearon los cafeteros a finales de los años cincuenta.",
    },
    {
        "topic": "Interbolsa: la caída de la mayor comisionista de bolsa de Colombia",
        "format": "investigacion",
        "region": "Latinoamérica",
        "hook": "En 2012 la mayor firma comisionista del país fue intervenida.",
    },
    {
        "topic": "DMG: la pirámide que enfrentó a Colombia",
        "format": "investigacion",
        "region": "Latinoamérica",
        "hook": "Prometía rendimientos imposibles y miles de personas pusieron allí sus ahorros.",
    },
    {
        "topic": "Postobón contra Coca-Cola en Colombia",
        "format": "rivalidad",
        "region": "Latinoamérica",
        "hook": "Postobón nació en Medellín en 1904, antes de que la Coca-Cola llegara al país.",
    },
    {
        "topic": "Bavaria: la cervecera colombiana que acabó en manos extranjeras",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "En 2005 SABMiller la compró por unos 7.800 millones de dólares.",
    },
    {
        "topic": "Corona: la cerveza mexicana que conquistó el mundo",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Nació en 1925 en la Ciudad de México.",
    },
    {
        "topic": "Oxxo: las tiendas de la esquina que cubrieron México",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Nació en 1978 en Monterrey para vender la cerveza de su propio grupo.",
    },
    {
        "topic": "Petrobras y el Lava Jato: el escándalo que empezó en un lavadero de coches",
        "format": "investigacion",
        "region": "Latinoamérica",
        "hook": "La investigación tomó su nombre de un lavadero de coches de Brasilia.",
    },
    {
        "topic": "Quilmes: la cerveza argentina que fundó un inmigrante alemán",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "La fundó en 1888 Otto Bemberg.",
    },
    {
        "topic": "Havanna: los alfajores que nacieron en Mar del Plata",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Nació en 1947 en Mar del Plata.",
    },
    {
        "topic": "Aerolíneas Argentinas: privatizada en 1990, recuperada por el Estado en 2008",
        "format": "auge_caida",
        "region": "Latinoamérica",
        "hook": "Pasó por varios dueños y acabó otra vez en manos del Estado.",
    },
    {
        "topic": "LAN y TAM: la fusión que creó la mayor aerolínea de Latinoamérica",
        "format": "rivalidad",
        "region": "Latinoamérica",
        "hook": "En 2012 una aerolínea chilena y una brasileña se unieron en LATAM.",
    },
    {
        "topic": "Falabella: de sastrería en Santiago a gigante del comercio",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Empezó en 1889 como una sastrería en Santiago de Chile.",
    },
    {
        "topic": "Interjet: la aerolínea mexicana que dejó de volar",
        "format": "auge_caida",
        "region": "Latinoamérica",
        "hook": "En 2020 dejó de volar con miles de pasajeros afectados.",
    },
    {
        "topic": "Pollo Campero: el pollo frito que viajaba en la maleta",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Los emigrantes guatemaltecos lo llevaban en el avión de vuelta a Estados Unidos.",
    },
    {
        "topic": "Arcor: el gigante de los caramelos que nació en un pueblo de Córdoba",
        "format": "cronologia",
        "region": "Latinoamérica",
        "hook": "Nació en 1951 en Arroyito, un pueblo de Córdoba (Argentina).",
    },
    {
        "topic": "Polaroid: la foto instantánea que no sobrevivió a lo digital",
        "format": "auge_caida",
        "region": "Mundo",
        "hook": "Su cámara revelaba la foto en un minuto ya a finales de los años cuarenta.",
    },
    {
        "topic": "Sears: el Amazon de hace cien años",
        "format": "errores",
        "region": "Mundo",
        "hook": "Por catálogo vendía de todo, hasta casas para montar.",
    },
    {
        "topic": "Lehman Brothers: el banco que nadie rescató",
        "format": "investigacion",
        "region": "Mundo",
        "hook": "Su quiebra en 2008 fue la mayor de la historia de Estados Unidos.",
    },
    {
        "topic": "Wirecard: los 1.900 millones que no existían",
        "format": "investigacion",
        "region": "Mundo",
        "hook": "En 2020 admitió que 1.900 millones de euros de su balance quizá no existían.",
    },
    {
        "topic": "Ferrari contra Lamborghini: el fabricante de tractores que desafió a Enzo",
        "format": "rivalidad",
        "region": "Mundo",
        "hook": "Ferruccio Lamborghini fabricaba tractores antes de hacer deportivos.",
    },
    {
        "topic": "Nike: de vender zapatillas en un coche a gigante mundial",
        "format": "cronologia",
        "region": "Mundo",
        "hook": "Phil Knight vendía zapatillas desde el maletero de su coche.",
    },
    {
        "topic": "Puig: la perfumera de Barcelona que conquistó el lujo mundial",
        "format": "cronologia",
        "region": "España",
        "hook": "Antonio Puig fundó la empresa en Barcelona en 1914.",
    },
]


def _key(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in text if ch.isalnum())


def _brand(topic: str) -> str:
    """La marca protagonista: lo que va antes de «:» o el principio del tema."""
    return _key(topic.split(":")[0].split(" contra ")[0])[:12]


def progress(done_topics: list[str]) -> tuple[int, int]:
    """Cuántas historias del banco ya se hicieron, de cuántas."""
    done = " ".join(_key(t) for t in done_topics)
    made = sum(1 for idea in IDEAS if _brand(idea["topic"]) in done)
    return made, len(IDEAS)


def fresh_ideas(done_topics: list[str], region: str = "", limit: int = 5) -> list[dict]:
    """Ideas que aún no se han hecho, alternando formatos (y regiones si no se pide una)."""
    done = " ".join(_key(t) for t in done_topics)
    pending = [
        idea
        for idea in IDEAS
        if (not region or idea["region"] == region) and _brand(idea["topic"]) not in done
    ]
    chosen: list[dict] = []
    while pending and len(chosen) < limit:
        formats = {i["format"] for i in chosen}
        last_region = chosen[-1]["region"] if chosen else ""
        # La primera que traiga un formato nuevo y cambie de región; si no hay, la que
        # cumpla lo más importante (formato nuevo), y si no, la siguiente.
        pick = pending[0]
        best = (True, True)
        for idea in pending:
            score = (idea["format"] in formats, idea["region"] == last_region)
            if score < best:
                pick, best = idea, score
        chosen.append(pick)
        pending.remove(pick)
    return chosen
