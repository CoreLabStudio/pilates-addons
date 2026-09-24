# -*- coding: utf-8 -*-
"""Making a private session should be picking a type, and nothing else.

Before these two types existed, every class type on the system was a group
class, so a one-off private session meant borrowing a group type and then
setting Session Type to Private afterwards. The order mattered and nothing
on screen said so: _onchange_class_type_id copies session_type off the type,
so choosing the type second put it back to Group and capacity back to 6 or
7 - a private session quietly open to five other people.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPrivateClassTypes(TransactionCase):

    longMessage = False

    def _new_class_form(self, class_type):
        """What the admin actually does: open New on the Schedule, pick a
        class type, and let the onchange fill the rest in."""
        Event = self.env["calendar.event"].with_context(
            default_is_fitness_class=True)
        start = fields.Datetime.now() + timedelta(days=2)
        event = Event.new({
            "name": False,
            "start": start,
            "stop": start + timedelta(minutes=60),
            "is_fitness_class": True,
        })
        event.class_type_id = class_type
        event._onchange_class_type_id()
        return event

    def test_both_private_types_exist(self):
        for xmlid in ("fitness_core.class_type_barre_private",
                      "fitness_core.class_type_reformer_private"):
            ct = self.env.ref(xmlid, raise_if_not_found=False)
            self.assertTrue(ct, "%s is missing" % xmlid)
            self.assertEqual(ct.session_type, "private",
                             "%s is not a private type" % xmlid)
            self.assertEqual(ct.max_capacity, 1,
                             "%s does not hold exactly one person" % xmlid)

    def test_picking_the_type_makes_the_session_private(self):
        """The whole point: no second step, nothing to remember."""
        for xmlid in ("fitness_core.class_type_barre_private",
                      "fitness_core.class_type_reformer_private"):
            ct = self.env.ref(xmlid)
            event = self._new_class_form(ct)
            self.assertEqual(
                event.session_type, "private",
                "%s did not carry Private onto the class" % ct.name)

    def test_capacity_becomes_one_without_being_typed(self):
        for xmlid in ("fitness_core.class_type_barre_private",
                      "fitness_core.class_type_reformer_private"):
            ct = self.env.ref(xmlid)
            event = self._new_class_form(ct)
            self.assertEqual(
                event.capacity, 1,
                "%s left room for somebody else" % ct.name)

    def test_the_room_comes_with_it(self):
        barre = self.env.ref("fitness_core.class_type_barre_private")
        event = self._new_class_form(barre)
        self.assertEqual(event.classroom_id,
                         self.env.ref("fitness_core.classroom_a_barre"))

    def test_the_old_trap_is_what_these_types_avoid(self):
        """Kept as the reason they exist: with a group type, setting Private
        first and choosing the type second silently undoes it."""
        group_type = self.env["fitness.class.type"].search(
            [("session_type", "=", "group")], limit=1)
        self.assertTrue(group_type, "no group type to demonstrate with")

        start = fields.Datetime.now() + timedelta(days=2)
        event = self.env["calendar.event"].new({
            "start": start, "stop": start + timedelta(minutes=60),
            "is_fitness_class": True,
            "session_type": "private",
        })
        event.class_type_id = group_type
        event._onchange_class_type_id()

        self.assertEqual(
            event.session_type, "group",
            "the ordering trap is gone - this test and the comment on the "
            "private class types are out of date")
