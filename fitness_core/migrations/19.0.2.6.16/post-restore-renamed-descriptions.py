# -*- coding: utf-8 -*-
"""Put the Barre descriptions back on the records students actually see.

WHAT WENT WRONG
---------------
Migration 19.0.1.0.1 loads these descriptions by NAME, and two of its keys are
"Barre Blast" and "Burn It Baby". The studio has since renamed those classes to
"Barre Pump it" and "Barre Groove" and left the originals archived, so that
lookup can no longer reach the live records - it matches nothing, because an
ordinary search skips archived rows. Both live class types have therefore
carried EMPTY descriptions in all three languages, while the client's copy sat
on the archived records under the old names.

WHERE THIS TEXT COMES FROM
--------------------------
The client's own document, not the archived records. The two are the same prose,
but the stored copy had drifted: "isometias" for "isometrias" and "glutis" for
"glutis" (accent lost) in the Groove text, and the trailing emoji stripped in all
three languages. Restoring from the record would have published those mistakes to
students, so the document wins and the drift is corrected here.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
  * It does not touch the archived "Barre Blast" and "Burn It Baby" records at
    all - not their text, not their active flag. They stay archived.
  * It writes `description` and nothing else. Level, intensity, price and every
    other field are left exactly as they are.
  * It skips any record that already has a description in that language, so an
    edit made by the studio is never overwritten. That also makes it re-runnable.
    "Already has" is read from the stored jsonb column, NOT from the ORM: a
    translatable field falls back to the source language when a translation is
    missing, so reading it through the ORM makes an untranslated record look
    populated as soon as en_US is written, and the other two languages get
    skipped.
  * It does not carry the document's "Focus:" and "Level:" lines. No other class
    description contains them, and Level is a separate field on the model; adding
    them to these two alone would make them inconsistent with the other four.

Fresh installs still get their descriptions from 19.0.1.0.1 as before; this only
repairs databases where the rename has already happened.
"""
import logging

_logger = logging.getLogger(__name__)

#: Keyed by the CURRENT name of each record. Text is verbatim from the client's
#: "Descripcion de clases" document.
_DESCRIPTIONS = {
    'Barre Pump it': {
        'en_US': (
            'Better known as Barre Blast, this is not your typical adult ballet class—it’s faster, '
            'stronger, and way more fun. Get ready for 30 minutes of high-energy barre work, '
            'combining technical ballet exercises with weights and props to fire up your muscles and '
            'boost strength and precision. Then, take it to the floor for an intense 15-minute barre '
            'burn that challenges your core, endurance, and control. All set to a powerful, feel-good '
            'playlist that keeps you moving, motivated, and pushing your limits. Barre Blast is where '
            'technique meets sweat—a dynamic, full-body workout that leaves you feeling strong, '
            'energized, and unstoppable.'
        ),
        'es_ES': (
            'Más conocida como Barre Blast, esta no es la típica clase de ballet para adultos: es más '
            'rápida, más intensa y mucho más divertida. Prepárate para 30 minutos de trabajo en barra '
            'de alta energía, combinando ejercicios técnicos de ballet con pesas y accesorios para '
            'activar tus músculos y potenciar la fuerza y la precisión. Después, pasamos al suelo con '
            '15 minutos intensos de floor barre que pondrán a prueba tu core, tu resistencia y tu '
            'control. Todo acompañado de una playlist potente y motivadora que te mantendrá en '
            'movimiento, concentrada y superando tus límites. Barre Blast es donde la técnica se '
            'encuentra con el esfuerzo: un entrenamiento dinámico de cuerpo completo que te hará '
            'sentir fuerte, llena de energía e imparable.'
        ),
        'ca_ES': (
            'Més coneguda com a Barre Blast, aquesta no és la típica classe de ballet per a adults: '
            'és més ràpida, més intensa i molt més divertida. Prepara’t per a 30 minuts de treball a '
            'la barra d’alta energia, combinant exercicis tècnics de ballet amb peses i accessoris '
            'per activar la musculatura i potenciar la força i la precisió. Després, passem al terra '
            'amb 15 minuts intensos de floor barre que posaran a prova el teu core, la teva '
            'resistència i el teu control. Tot acompanyat d’una playlist potent i motivadora que et '
            'mantindrà en moviment, concentrada i superant els teus límits. Barre Blast és on la '
            'tècnica es troba amb l’esforç: un entrenament dinàmic de cos complet que et farà sentir '
            'forta, plena d’energia i imparable.'
        ),
    },
    'Barre Groove': {
        'en_US': (
            'Burn It Baby is your ultimate lower-body burner—designed to sculpt, lift, and set your '
            'glutes on fire. This high-intensity class zeroes in on the glute muscles while firing up '
            'your core, combining resistance, mobility, and control for serious, full-body results. '
            'Get ready for deep isometric holds, relentless slow pulses, and sliding exercises that '
            'push your muscles to the limit. Your core stays constantly engaged, building strength, '
            'stability, and control with every move. It’s all about that shake, that burn, and that '
            'unstoppable energy. Feel it. Fight it. Love it. 🔥'
        ),
        'es_ES': (
            'Burn It Baby es tu entrenamiento definitivo de tren inferior, diseñado para esculpir, '
            'elevar y hacer arder tus glúteos. Esta clase de alta intensidad se centra en los '
            'músculos glúteos mientras activa constantemente el core, combinando resistencia, '
            'movilidad y control para conseguir resultados potentes en todo el cuerpo. Prepárate para '
            'isometrías profundas, pulsos lentos e intensos y ejercicios de deslizamiento que llevan '
            'tus músculos al límite. Tu core trabaja en todo momento, desarrollando fuerza, '
            'estabilidad y control en cada movimiento. Aquí se trata de ese temblor, ese burn y esa '
            'energía imparable. Siéntelo. Supéralo. Disfrútalo. 🔥'
        ),
        'ca_ES': (
            'Burn It Baby és el teu entrenament definitiu de tren inferior, dissenyat per esculpir, '
            'elevar i fer cremar els teus glutis. Aquesta classe d’alta intensitat se centra en els '
            'músculs glútis mentre activa constantment el core, combinant resistència, mobilitat i '
            'control per aconseguir resultats potents a tot el cos. Prepara’t per a isometries '
            'profundes, polsos lents i intensos i exercicis de lliscament que porten els teus músculs '
            'al límit. El teu core treballa en tot moment, desenvolupant força, estabilitat i control '
            'en cada moviment. Aquí tot va d’aquell tremolor, aquell burn i aquella energia '
            'imparable. Sent-ho. Supera-ho. Gaudeix-ho. 🔥'
        ),
    },
}


def migrate(cr, version):
    if not version:
        # fresh install - 19.0.1.0.1 has already seeded these
        return

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    ClassType = env['fitness.class.type']

    written = 0
    for class_name, translations in _DESCRIPTIONS.items():
        rec = ClassType.search([('name', '=', class_name)], limit=1)
        if not rec:
            _logger.warning(
                "fitness_core: class type %r not found - description not restored.",
                class_name)
            continue

        # Read what is actually stored, per language, straight from the jsonb.
        cr.execute("SELECT description FROM fitness_class_type WHERE id = %s",
                   (rec.id,))
        row = cr.fetchone()
        stored = row[0] if row and row[0] else {}

        for lang_code, text in translations.items():
            if (stored.get(lang_code) or '').strip():
                _logger.info(
                    "fitness_core: %r already has a %s description - left alone.",
                    class_name, lang_code)
                continue
            rec.with_context(lang=lang_code).write({'description': text})
            written += 1
            _logger.info("fitness_core: restored %s description for %r.",
                         lang_code, class_name)

    _logger.info("fitness_core: %d description(s) restored.", written)
