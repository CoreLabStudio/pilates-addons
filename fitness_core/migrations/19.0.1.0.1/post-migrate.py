import logging
_logger = logging.getLogger(__name__)

_DESCRIPTIONS = {
    'Barre Harmony': {
        'en_US': (
            "Barre Harmony is a dynamic class designed to help you tone, sweat, and enjoy movement "
            "to a classic, feel-good playlist. This low-impact workout is based on isometric exercises "
            "that target and strengthen deep muscle groups, improving both stability and endurance. "
            "The class emphasizes precise technique and controlled movement, helping you build body "
            "awareness and alignment. It incorporates elements of functional Pilates, while primarily "
            "drawing inspiration from ballet-inspired movements. Barre Harmony is accessible and "
            "welcoming, making it an excellent choice for beginners as well as anyone looking for a "
            "mindful yet effective workout."
        ),
        'es_ES': (
            "Barre Harmony es una clase dinámica diseñada para ayudarte a tonificar, sudar y "
            "disfrutar del movimiento con una selección musical clásica y motivadora. Este "
            "entrenamiento de bajo impacto se basa en ejercicios isométricos que trabajan y "
            "fortalecen los músculos profundos, mejorando tanto la estabilidad como la resistencia. "
            "La clase pone énfasis en la técnica precisa y el control del movimiento, "
            "ayudándote a desarrollar conciencia corporal y una mejor alineación. Incorpora "
            "elementos del Pilates funcional, aunque se inspira principalmente en movimientos de ballet. "
            "Barre Harmony es accesible y acogedora, lo que la convierte en una excelente opción "
            "tanto para principiantes como para cualquier persona que busque un entrenamiento consciente "
            "y efectivo."
        ),
        'ca_ES': (
            "Barre Harmony és una classe dinàmica dissenyada per ajudar-te a tonificar, suar "
            "i gaudir del moviment amb una selecció musical clàssica i motivadora. Aquest "
            "entrenament de baix impacte es basa en exercicis isomètrics que treballen i enforteixen "
            "la musculatura profunda, millorant tant l'estabilitat com la resistència. La classe "
            "posa èmfasi en la tècnica precisa i el control del moviment, ajudant-te a "
            "desenvolupar consciència corporal i una millor alineació. Incorpora elements del "
            "Pilates funcional, tot i que s'inspira principalment en moviments de ballet. Barre Harmony "
            "és accessible i acollidora, fet que la converteix en una excel·lent opció "
            "tant per a principiants com per a qualsevol persona que busqui un entrenament conscient "
            "i efectiu."
        ),
    },
    'Barre Blast': {
        'en_US': (
            "Better known as Barre Blast, this is not your typical adult ballet class—it's faster, "
            "stronger, and way more fun. Get ready for 30 minutes of high-energy barre work, combining "
            "technical ballet exercises with weights and props to fire up your muscles and boost strength "
            "and precision. Then, take it to the floor for an intense 15-minute barre burn that challenges "
            "your core, endurance, and control. All set to a powerful, feel-good playlist that keeps you "
            "moving, motivated, and pushing your limits. Barre Blast is where technique meets "
            "sweat—a dynamic, full-body workout that leaves you feeling strong, energized, and "
            "unstoppable."
        ),
        'es_ES': (
            "Más conocida como Barre Blast, esta no es la típica clase de ballet para adultos: "
            "es más rápida, más intensa y mucho más divertida. Prepárate para "
            "30 minutos de trabajo en barra de alta energía, combinando ejercicios técnicos de "
            "ballet con pesas y accesorios para activar tus músculos y potenciar la fuerza y la "
            "precisión. Después, pasamos al suelo con 15 minutos intensos de floor barre que "
            "pondrán a prueba tu core, tu resistencia y tu control. Todo acompañado de una "
            "playlist potente y motivadora que te mantendrá en movimiento, concentrada y superando "
            "tus límites. Barre Blast es donde la técnica se encuentra con el esfuerzo: un "
            "entrenamiento dinámico de cuerpo completo que te hará sentir fuerte, llena de "
            "energía e imparable."
        ),
        'ca_ES': (
            "Més coneguda com a Barre Blast, aquesta no és la típica classe de ballet per "
            "a adults: és més ràpida, més intensa i molt més divertida. "
            "Prepara't per a 30 minuts de treball a la barra d'alta energia, combinant exercicis "
            "tècnics de ballet amb peses i accessoris per activar la musculatura i potenciar la "
            "força i la precisió. Després, passem al terra amb 15 minuts intensos de "
            "floor barre que posaran a prova el teu core, la teva resistència i el teu control. "
            "Tot acompanyat d'una playlist potent i motivadora que et mantindrà en moviment, "
            "concentrada i superant els teus límits. Barre Blast és on la tècnica es "
            "troba amb l'esforç: un entrenament dinàmic de cos complet que et farà sentir "
            "forta, plena d'energia i imparable."
        ),
    },
    'Burn It Baby': {
        'en_US': (
            "Burn It Baby is your ultimate lower-body burner—designed to sculpt, lift, and set your "
            "glutes on fire. This high-intensity class zeroes in on the glute muscles while firing up your "
            "core, combining resistance, mobility, and control for serious, full-body results. Get ready "
            "for deep isometric holds, relentless slow pulses, and sliding exercises that push your muscles "
            "to the limit. Your core stays constantly engaged, building strength, stability, and control "
            "with every move. It's all about that shake, that burn, and that unstoppable energy. Feel it. "
            "Fight it. Love it."
        ),
        'es_ES': (
            "Burn It Baby es tu entrenamiento definitivo de tren inferior, diseñado para esculpir, "
            "elevar y hacer arder tus glúteos. Esta clase de alta intensidad se centra en los "
            "músculos glúteos mientras activa constantemente el core, combinando resistencia, "
            "movilidad y control para conseguir resultados potentes en todo el cuerpo. Prepárate "
            "para isometías profundas, pulsos lentos e intensos y ejercicios de deslizamiento que "
            "llevan tus músculos al límite. Tu core trabaja en todo momento, desarrollando "
            "fuerza, estabilidad y control en cada movimiento. Aquí se trata de ese temblor, ese "
            "burn y esa energía imparable. Siéntelo. Supéralo. Disfrútalo."
        ),
        'ca_ES': (
            "Burn It Baby és el teu entrenament definitiu de tren inferior, dissenyat per esculpir, "
            "elevar i fer cremar els teus glutis. Aquesta classe d'alta intensitat se centra en els "
            "músculs glutis mentre activa constantment el core, combinant resistència, "
            "mobilitat i control per aconseguir resultats potents a tot el cos. Prepara't per a "
            "isometries profundes, polsos lents i intensos i exercicis de lliscament que porten els teus "
            "músculs al límit. El teu core treballa en tot moment, desenvolupant força, "
            "estabilitat i control en cada moviment. Aquí tot va d'aquell tremolor, aquell burn i "
            "aquella energia imparable. Sent-ho. Supera-ho. Gaudeix-ho."
        ),
    },
    'Reformer FlowLab': {
        'en_US': (
            "This routine is designed at a slower, more controlled pace, focusing on movements that "
            "incorporate open rotations and twisting patterns. The emphasis is on depth, precision, and "
            "fluidity—allowing you to move with intention and control. Longer in duration and "
            "stronger in impact, this style of training builds mobility, strength, and body awareness "
            "while helping you connect more deeply with each movement."
        ),
        'es_ES': (
            "Esta rutina está diseñada a un ritmo más lento y controlado, centrada en "
            "movimientos que incorporan rotaciones abiertas y patrones de torsión. El énfasis "
            "está en la profundidad, la precisión y la fluidez, permitiéndote moverte con "
            "intención y control. Más larga en duración y más intensa en su impacto, "
            "este estilo de entrenamiento desarrolla la movilidad, la fuerza y la conciencia corporal, "
            "ayudándote a conectar de forma más profunda con cada movimiento."
        ),
        'ca_ES': (
            "Aquesta rutina està dissenyada a un ritme més lent i controlat, centrada en "
            "moviments que incorporen rotacions obertes i patrons de torsió. L'èmfasi es posa "
            "en la profunditat, la precisió i la fluïdesa, permetent-te moure't amb intenció "
            "i control. Més llarga en durada i amb un impacte més intens, aquest estil "
            "d'entrenament desenvolupa la mobilitat, la força i la consciència corporal, "
            "ajudant-te a connectar de manera més profunda amb cada moviment."
        ),
    },
    'Reformer Sculpt': {
        'en_US': (
            "This is core training turned all the way up. Designed to build unstoppable stamina, these "
            "routines keep your core under constant fire from start to finish. With fewer exercises and "
            "lightning-fast transitions, your heart rate stays high while your abs, obliques, and deep "
            "core muscles work non-stop to stabilize, power, and control every move. No breaks, no "
            "escape—just pure core activation. Each session finishes with an intense burnout that "
            "pushes your endurance to the edge and leaves your core shaking. Strong core. High intensity. "
            "No limits."
        ),
        'es_ES': (
            "Esto es entrenamiento de core llevado al máximo. Diseñado para construir una "
            "resistencia imparable, estas rutinas mantienen tu core en constante activación de "
            "principio a fin. Con menos ejercicios y transiciones rápidas, tu frecuencia cardíaca "
            "se mantiene alta mientras tus abdominales, oblicuos y musculatura profunda trabajan sin "
            "descanso para estabilizar, impulsar y controlar cada movimiento. Sin pausas, sin escapatoria: "
            "pura activación. Cada sesión termina con un burnout intenso que lleva tu "
            "resistencia al límite y deja tu core temblando. Core fuerte. Alta intensidad. "
            "Sin límites."
        ),
        'ca_ES': (
            "Això és entrenament de core portat al màxim. Dissenyat per construir una "
            "resistència imparable, aquestes rutines mantenen el teu core en activació constant "
            "de principi a fi. Amb menys exercicis i transicions ràpides, la teva freqüència "
            "cardíaca es manté alta mentre els abdominals, els oblics i la musculatura profunda "
            "treballen sense descans per estabilitzar, impulsar i controlar cada moviment. Sense pauses, "
            "sense escapament: pura activació. Cada sessió acaba amb un burnout intens que porta "
            "la teva resistència al límit i deixa el teu core tremolant. Core fort. Alta "
            "intensitat. Sense límits."
        ),
    },
    'Reformer Extreme (BURN!!!)': {
        'en_US': (
            "BURN!!! Is a full-on, high-intensity blast powered by an electrifying playlist that keeps "
            "your energy at maximum from the very first beat. This class is designed to spike your heart "
            "rate and keep it there, combining fast, dynamic movements with weights, a fit ball, and a fit "
            "circle for a seriously effective burn. Expect non-stop action, full-body engagement, and an "
            "addictive rhythm that pushes you harder every second. It's sweaty, it's powerful, and it hits "
            "different every time. You won't just feel it—you'll be blown away."
        ),
        'es_ES': (
            "BURN!!! Es una explosión de alta intensidad impulsada por una playlist electrizante que "
            "mantiene tu energía al máximo desde el primer beat. Esta clase está diseñada "
            "para disparar tu frecuencia cardíaca y mantenerla arriba, combinando movimientos "
            "rápidos y dinámicos con pesas, fit ball y fit circle para un burn brutal. "
            "Prepárate para acción sin pausa, activación total del cuerpo y un ritmo "
            "adictivo que te empuja a dar más en cada segundo. Es sudor, es potencia y es una "
            "experiencia que se siente diferente cada vez. No solo lo vas a sentir… te va a "
            "sorprender."
        ),
        'ca_ES': (
            "BURN!!! És una explosió d'alta intensitat impulsada per una playlist "
            "electritzant que manté la teva energia al màxim des del primer beat. Aquesta "
            "classe està dissenyada per disparar la teva freqüència cardíaca i "
            "mantenir-la alta, combinant moviments ràpids i dinàmics amb manuelles, fit ball "
            "i fit circle per a un burn brutal. Prepara't per a acció sense pausa, activació "
            "total del cos i un ritme addictiu que t'empeny a donar més a cada segon. És suor, "
            "és potència i és una experiència que es viu diferent cada vegada. No "
            "només ho sentiràs… et sorprendrà."
        ),
    },
}

# Flow Reformer (id≈5) is intentionally skipped — its name does not clearly
# map to any of the provided descriptions. Flag for manual review.
_AMBIGUOUS = ['Flow Reformer']


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    ClassType = env['fitness.class.type']

    loaded = 0
    for class_name, translations in _DESCRIPTIONS.items():
        rec = ClassType.search([('name', '=', class_name)], limit=1)
        if not rec:
            _logger.warning(
                "[MIGRATE 19.0.1.0.1] fitness.class.type '%s' not found — skipping description.",
                class_name,
            )
            continue
        for lang_code, text in translations.items():
            try:
                rec.with_context(lang=lang_code).write({'description': text})
            except Exception:
                _logger.exception(
                    "[MIGRATE 19.0.1.0.1] Failed to write %s description for '%s'.",
                    lang_code, class_name,
                )
        loaded += 1
        _logger.info("[MIGRATE 19.0.1.0.1] Loaded descriptions for '%s'.", class_name)

    for ambiguous_name in _AMBIGUOUS:
        _logger.warning(
            "[MIGRATE 19.0.1.0.1] '%s' skipped — name is ambiguous and no matching "
            "description was provided. Please update manually.",
            ambiguous_name,
        )

    _logger.info("[MIGRATE 19.0.1.0.1] Done. %d class type(s) updated.", loaded)
