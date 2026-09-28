# -*- coding: utf-8 -*-
"""The Organizer picker offers instructors, and only instructors.

The field is labelled Instructor and was offered every account on the
database - 136 of them, students included - because nothing restricted
it. Picking a student is not merely a wrong label. The instructor portal
is gated on being the class's organiser:

    if not event.exists() or event.user_id.id != request.env.user.id:
        return redirect(...)

so a student set as Organizer would open /my/instructor and read that
class's full roster, every other student's name on it. Since the
attendance guard allows "the instructor whose class it is", she could
mark attendance on it too.

A domain, not a constraint, and the difference is the point: six
upcoming classes on production are organised by OdooBot because the
nightly cron creates them under itself. A constraint would refuse to
save them. A domain filters what is offered and leaves what is stored
alone.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrganizerIsAnInstructor(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Organizer Teacher",
                "login": "organizer.teacher@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_teacher").id,
                ])],
            })
        cls.student = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Organizer Student",
                "login": "organizer.student@example.invalid",
                "group_ids": [(6, 0, [
                    cls.env.ref("base.group_portal").id,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })

    # ── the searchable flag the domain is built on ──────────────────────────

    def test_the_flag_the_domain_uses_tells_them_apart(self):
        Users = self.env["res.users"]
        offered = Users.search([("fitness_is_teacher", "=", True)])
        self.assertIn(
            self.teacher, offered,
            "an instructor is not offered by the domain")
        self.assertNotIn(
            self.student, offered,
            "a student is offered as an Organizer; she would get the "
            "roster of any class she was put on")

    def test_the_negative_search_is_the_mirror_of_it(self):
        """A half-working search would quietly offer everybody."""
        Users = self.env["res.users"]
        not_offered = Users.search([("fitness_is_teacher", "=", False)])
        self.assertIn(self.student, not_offered)
        self.assertNotIn(self.teacher, not_offered)

    # ── the form actually carries it ────────────────────────────────────────

    def test_the_form_restricts_the_organizer_field(self):
        arch = self.env["calendar.event"].get_view(view_type="form")["arch"]
        self.assertIn(
            "fitness_is_teacher", arch,
            "the Organizer field on the form is unrestricted, so every "
            "account on the database is still offered")

    # ── what it must NOT do ─────────────────────────────────────────────────

    def test_a_class_already_organised_by_a_non_instructor_still_saves(self):
        """Six upcoming classes on production are organised by OdooBot.

        A domain filters the dropdown. It must not re-validate what is
        already stored, or those six become unsaveable.
        """
        odoobot = self.env.ref("base.user_root")
        start = fields.Datetime.now() + timedelta(days=2)
        event = self.env["calendar.event"].sudo().create({
            "name": "Organizer legacy class",
            "start": start,
            "stop": start + timedelta(minutes=55),
            "is_fitness_class": True,
            "user_id": odoobot.id,
        })
        self.assertEqual(event.user_id, odoobot, "fixture wrong")

        # editing something else on it must still work
        event.write({"name": "Organizer legacy class, renamed"})
        self.assertEqual(
            event.user_id, odoobot,
            "saving an unrelated change dropped the existing organiser")
        self.assertFalse(
            odoobot.fitness_is_teacher,
            "fixture wrong: OdooBot is not supposed to be an instructor")

    def test_an_instructor_can_still_be_set_normally(self):
        start = fields.Datetime.now() + timedelta(days=2)
        event = self.env["calendar.event"].sudo().create({
            "name": "Organizer normal class",
            "start": start,
            "stop": start + timedelta(minutes=55),
            "is_fitness_class": True,
            "user_id": self.teacher.id,
        })
        self.assertEqual(event.user_id, self.teacher)
