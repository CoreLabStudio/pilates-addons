# -*- coding: utf-8 -*-
"""The "cannot open the shop" warning is for students, not instructors.

Its condition was "a portal account without the student group", which is
also the exact shape of an instructor. So it fired on all four of them -
Agostina, Maridelvis, Demo Teacher, and Raquel the day she was created -
and told the studio each of them "signed up but never got through email
verification". None of them signed up as a student.

The warning was not lying about the shop: the gate really is the student
group, and an instructor really cannot open it. What was wrong was the
explanation and the implied action. Giving an instructor shop access is a
decision somebody makes in Settings, not a stuck signup to repair.

A warning that is wrong four times out of four stops being read, and
every instructor added made the list noisier.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestShopWarningNotForInstructors(TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal = cls.env.ref("base.group_portal").id
        cls.instructor = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Warning Instructor",
                "login": "warning.instructor@example.invalid",
                "group_ids": [(6, 0, [
                    portal,
                    cls.env.ref("fitness_core.group_fitness_teacher").id,
                ])],
            })
        cls.stuck_student = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Warning Stuck Student",
                "login": "warning.stuck@example.invalid",
                "group_ids": [(6, 0, [portal])],
            })
        cls.good_student = cls.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Warning Good Student",
                "login": "warning.good@example.invalid",
                "group_ids": [(6, 0, [
                    portal,
                    cls.env.ref("fitness_core.group_fitness_student").id,
                ])],
            })

    def _shows_warning(self, user):
        """The view's own condition, evaluated on the record.

        invisible="fitness_is_verified_student or not share
                   or fitness_is_teacher"
        """
        return not (user.fitness_is_verified_student
                    or not user.share
                    or user.fitness_is_teacher)

    # ── the case it exists for ──────────────────────────────────────────────

    def test_a_stuck_student_still_gets_the_warning(self):
        """The positive. Removing the noise must not remove the signal."""
        self.assertTrue(
            self._shows_warning(self.stuck_student),
            "a portal account with no student group is exactly who this "
            "warning is for, and it no longer fires")

    # ── the noise it must stop making ───────────────────────────────────────

    def test_an_instructor_does_not_get_it(self):
        self.assertTrue(
            self.instructor.share, "fixture wrong: not a portal account")
        self.assertFalse(
            self.instructor.fitness_is_verified_student,
            "fixture wrong: she is not supposed to hold the student group")
        self.assertFalse(
            self._shows_warning(self.instructor),
            "an instructor is told she 'signed up but never got through "
            "email verification', which she never did")

    def test_a_student_who_can_shop_does_not_get_it(self):
        self.assertFalse(self._shows_warning(self.good_student))

    def test_an_internal_user_does_not_get_it(self):
        internal = self.env["res.users"].with_context(
            no_reset_password=True).create({
                "name": "Warning Internal",
                "login": "warning.internal@example.invalid",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            })
        self.assertFalse(
            internal.share, "fixture wrong: should not be a portal account")
        self.assertFalse(self._shows_warning(internal))

    # ── and the view carries the condition ──────────────────────────────────

    def test_the_form_checks_the_instructor_flag(self):
        arch = self.env["res.users"].get_view(
            view_id=self.env.ref(
                "fitness_portal.view_student_profile_simple").id,
            view_type="form")["arch"]
        self.assertIn(
            "fitness_is_teacher", arch,
            "the warning's condition does not look at whether she is an "
            "instructor, so it still fires on every one of them")
