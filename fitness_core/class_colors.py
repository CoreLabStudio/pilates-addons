# -*- coding: utf-8 -*-
"""Colour coding for the two disciplines.

Reformer reads blue, Barre reads brown, so a student can tell the two apart on
the timetable at a glance rather than having to remember which tab they left
selected. Within each family the shade runs light -> deep with how hard the
class is.

Three tiers, not one shade per class type. The studio runs twenty class types;
twenty shades of two hues are not tellable apart in a list, which is what the
coding exists for. Three are.

The tier comes from the class type's own ``intensity`` field wherever it is
set. Nine of the twenty types have none recorded - including most of the Barre
ones actually on the timetable - so those are placed by name below. Fill in
intensity in Odoo and this table stops being needed for that type.

The name fallback keys on the English name with punctuation stripped, which is
also what folds the mojibake "Quick & Dirty" duplicates onto the
same key as the real one. Class type names are not translated today (only
en_US exists); if they ever are, the fallback for that type stops matching and
it lands on the default tier, so prefer setting intensity.

The public website carries the same mapping in src/lib/discipline-colors.ts.
It is a static mirror and cannot read Odoo, so if intensity changes here the
two surfaces will disagree until that file is re-synced.
"""

LIGHT = 'light'
MID = 'mid'
DEEP = 'deep'
DEFAULT_TIER = MID

#: The studio's own intensity scale, folded onto three tiers.
INTENSITY_TIER = {
    'low': LIGHT,
    'low_moderate': LIGHT,
    'moderate': MID,
    'moderate_high': MID,
    'high': DEEP,
    'very_high': DEEP,
}

#: Types with no intensity recorded, placed by name.
NAME_TIER = {
    # Reformer
    'reformertone': LIGHT,
    'reformerpumpit': DEEP,
    # Barre
    'barreclassicflow': LIGHT,
    'barregroove': MID,
    'barrepumpit': DEEP,
    'burnbarre': DEEP,
    # Runs in both rooms at lunch, so it appears under either discipline and
    # takes that discipline's family.
    'quickdirtylunchclass': MID,
}


def normalize(name):
    """Letters and digits only, lowercased.

    Collapses spacing, punctuation and the mangled en dash in the duplicated
    "Quick & Dirty" records onto one key.
    """
    return ''.join(c for c in (name or '').lower() if c.isalnum() and c.isascii())


def tier_for(class_type):
    """Return 'light' | 'mid' | 'deep' for a fitness.class.type record."""
    tier = INTENSITY_TIER.get(class_type.intensity)
    if tier:
        return tier
    return NAME_TIER.get(normalize(class_type.name), DEFAULT_TIER)


def solid_class(discipline):
    """One flat colour per discipline: 'mv-solid-reformer' or 'mv-solid-barre'.

    This is what the portal actually uses today - the timetable badges and the
    selected toggle pill are the same colour, so the page reads as one
    discipline rather than as a gradient of unexplained shades.
    """
    if discipline not in ('reformer', 'barre'):
        discipline = 'reformer'
    return 'mv-solid-%s' % discipline


def css_class(discipline, tier):
    """RESERVED FOR THE CALENDAR VIEW, NOT YET BUILT.

    The chip class for one tier, e.g. 'mv-shade-reformer-deep'.

    The three-shade breakdown is deliberately not used on the timetable list.
    A list is read a column at a time, and three blues down one column read as
    three unrelated things rather than one discipline at three intensities. On
    a calendar, where different class types sit side by side in the same row,
    the shade is the only thing telling them apart - that is where this earns
    its keep. Until that view exists, use solid_class above.

    Background and text colour are set together by that one class; they were
    measured as a pair and must never be combined independently.
    """
    if discipline not in ('reformer', 'barre'):
        discipline = 'reformer'
    if tier not in (LIGHT, MID, DEEP):
        tier = DEFAULT_TIER
    return 'mv-shade-%s-%s' % (discipline, tier)
