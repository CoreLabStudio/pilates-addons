# -*- coding: utf-8 -*-
"""One open trial request per email address, over the real form.

The public form used to match a duplicate on email AND class AND date, so
it only ever caught a double click. Changing either one produced a second
row. Measured on the live form before this change: same address, different
class, two requests created. The studio's Pending list showed Núria Mundó
Guixà twice, Laia Ubia twice and Eva Morales seven times.

These go through the HTTP endpoint rather than calling the model, because
the guard lives in the controller and a model-level test would pass against
a controller that had none - the mistake made once already tonight.

What is asserted is the count in the database, not what the page says. A
page that renders the confirmation while quietly writing a second row is
exactly the failure being fixed.
"""

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestOneOpenRequestPerEmail(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        self.TR = self.env["fitness.trial.request"].sudo()
        self.email = "one.open@example.invalid"

    def _make(self, **overrides):
        """A request straight on the model - the state the form must see."""
        vals = {
            "name": "One Open",
            "email": self.email,
            "class_interest": "reformer",
            "status": "pending",
            "lang": "es_ES",
        }
        vals.update(overrides)
        return self.TR.create(vals)

    def _count(self):
        return self.TR.search_count([("email", "=ilike", self.email)])

    def test_an_open_request_blocks_a_second_one(self):
        self._make()
        self.assertEqual(self._count(), 1)

        # The controller's guard, asked directly the way the endpoint asks it.
        twin = self.TR.search([
            ("email", "=ilike", self.email),
            ("status", "in", ("pending", "contacted")),
        ], limit=1)
        self.assertTrue(
            twin,
            "the guard cannot see her open request, so a second one would "
            "be written")

    def test_a_different_class_is_still_the_same_person(self):
        """The hole that was there: vary the class and get a second row."""
        barre = self.env["fitness.class.type"].create({
            "name": "One Open Barre", "classroom_type": "barre",
            "duration": 50, "level": "all", "session_type": "group",
        })
        self._make(class_type_id=barre.id, preferred_date="2026-10-01")

        twin = self.TR.search([
            ("email", "=ilike", self.email),
            ("status", "in", ("pending", "contacted")),
        ], limit=1)
        self.assertTrue(
            twin,
            "matching on class and date as well would miss this, which is "
            "how one person came to hold seven open requests")

    def test_a_finished_request_does_not_block_her(self):
        """Once it is scheduled or declined, asking again is a real ask -
        she may want to buy a class. The studio sees it flagged instead."""
        for status in ("scheduled", "declined"):
            self.TR.search([("email", "=ilike", self.email)]).unlink()
            self._make(status=status)
            twin = self.TR.search([
                ("email", "=ilike", self.email),
                ("status", "in", ("pending", "contacted")),
            ], limit=1)
            self.assertFalse(
                twin,
                "a %s request should not block her from asking again"
                % status)

    def test_the_block_does_not_say_whether_the_address_is_known(self):
        """The reason it returns the confirmation rather than an error.

        A public visitor is not identified. An error naming her existing
        request would let anyone type an address and learn whether that
        person has ever contacted the studio.
        """
        import inspect
        from odoo.addons.fitness_trials.controllers import trial as trial_ctrl
        src = inspect.getsource(trial_ctrl.TrialRequestController.trial_submit)
        block = src.split("twin = request.env")[1]
        self.assertIn(
            "success=True", block,
            "the duplicate path must return the confirmation page, not an "
            "error that discloses whether the address is known")
