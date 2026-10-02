# -*- coding: utf-8 -*-
"""Recognising somebody by her phone when the address is new.

A person whose free trial is spent can ask again from the public website
under a different email, and nothing connects the two. The studio wants to
know, so it can ring her and ask for payment rather than booking a second
free class.

Three things this deliberately is not:

  it does not block anything - the submission goes through exactly as
  before, and approval refuses exactly as before;

  it is not the Trial Used flag - that one means "she has had her trial"
  and agrees with approval, while this is a guess from a number, so it has
  its own wording and its own column;

  and it is invisible to the person submitting. A public visitor who types
  a number must not learn from the response whether it is known here - the
  same reason the duplicate guard answers with the confirmation page.

Every number used here is checked against the database first. The production
restore carries real students with real phones, and a number invented in a
fixture that happens to be one of theirs would flag - or fail to flag - for
reasons that have nothing to do with what is being tested.
"""

from datetime import date, timedelta
import re

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged


class PhoneMatchFixture:

    @classmethod
    def _build(cls):
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.opening_date", "")
        # The trial offer has a deadline, and it lapsed on 30 September
        # 2026. fitness_portal falls back to a hardcoded
        # TRIAL_OFFER_END_DEFAULT when the parameter is unset, so from
        # 1 October every test that needs a claimable trial began failing
        # on the calendar rather than on anything it asserts. Pinned here
        # so these keep testing what they name.
        cls.env["ir.config_parameter"].sudo().set_param(
            "fitness.trial_offer_end", "2099-12-31")
        cls.TR = cls.env["fitness.trial.request"].sudo()
        cls.trial_product = cls.TR._all_trial_products()[:1]
        partners = cls.env["res.partner"].sudo().with_context(
            active_test=False).search([("phone", "!=", False)])
        cls._taken = {cls.TR._phone_key(p.phone) for p in partners}
        cls._taken.discard("")

    def _free_number(self):
        """Nine digits nobody on this database is already using."""
        n = 612000000
        while str(n) in self._taken:
            n += 1
        self._taken.add(str(n))
        return str(n)

    def _student(self, suffix, phone, spend_trial=True):
        partner = self.env["res.partner"].create({
            "name": "Phone %s" % suffix,
            "email": "phone.%s@example.invalid" % suffix,
            "phone": phone,
        })
        if spend_trial:
            order = self.env["sale.order"].sudo().create(
                {"partner_id": partner.id})
            self.env["sale.order.line"].sudo().create({
                "order_id": order.id,
                "product_id": self.trial_product.product_variant_ids[:1].id,
                "product_uom_qty": 1, "price_unit": 0.0,
            })
            order.action_confirm()
            self.assertEqual(
                order.amount_total, 0.0,
                "fixture wrong: a trial that costs money is not a free one")
        self.env.flush_all()
        return partner

    def _request(self, phone, email="stranger@example.invalid", **vals):
        base = {
            "name": "Someone Else",
            "email": email,
            "phone": phone,
            "class_interest": "reformer",
            "status": "pending",
            "lang": "en_US",
        }
        base.update(vals)
        req = self.TR.create(base)
        # A public submission arrives unattached; the email is a stranger's.
        req.partner_id = False
        self.env.invalidate_all()
        return req


@tagged("post_install", "-at_install")
class TestPhoneMatchesSpentStudent(PhoneMatchFixture, TransactionCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()

    # -- 1. the case it exists for, and its negative -------------------------

    def test_a_new_address_on_a_spent_students_number_is_flagged(self):
        number = self._free_number()
        self._student("spent", number)
        req = self._request(number)
        self.assertTrue(
            req.phone_matches_spent_student,
            "a request on a spent student's number was not flagged")
        self.assertIn(
            "Phone spent", req.phone_match_warning or "",
            "the warning does not name who the number belongs to")

    def test_the_same_number_on_a_student_who_has_NOT_used_her_trial(self):
        """Flagging her would be wrong - she is entitled to a trial."""
        number = self._free_number()
        self._student("unspent", number, spend_trial=False)
        req = self._request(number)
        self.assertFalse(
            req.phone_matches_spent_student,
            "a student who has never had a trial was reported as having "
            "used one")

    # -- 3. every way a person writes a Spanish number -----------------------

    def test_the_same_number_written_five_ways_all_match(self):
        number = self._free_number()
        a, b, c = number[:3], number[3:6], number[6:]
        written_five_ways = [
            "%s %s %s %s" % (a, b[:2], b[2:] + c[:1], c[1:]),
            "+34 %s" % number,
            "0034%s" % number,
            "%s-%s-%s" % (a, b, c),
            "(%s) %s%s" % (a, b, c),
        ]
        self._student("written", written_five_ways[0])
        for i, written in enumerate(written_five_ways):
            req = self._request(written, email="w%d@example.invalid" % i)
            self.assertTrue(
                req.phone_matches_spent_student,
                "%r was not recognised as the same number" % written)

    def test_a_different_number_does_not_match(self):
        """The negative for the above: normalising must not make
        everything match everything."""
        self._student("other", self._free_number())
        req = self._request(self._free_number())
        self.assertFalse(
            req.phone_matches_spent_student,
            "an unrelated number matched - normalising went too far")

    # -- 4. nothing to compare -----------------------------------------------

    def test_a_blank_phone_never_matches(self):
        self._student("blankcase", self._free_number())
        for empty in (False, "", "   "):
            req = self._request(empty)
            self.assertFalse(
                req.phone_matches_spent_student,
                "a request with no number matched somebody")
            self.assertFalse(req.phone_match_warning)

    def test_a_short_number_never_matches(self):
        """Three digits would match half the studio."""
        number = self._free_number()
        self._student("shortcase", number)
        for keep in (3, 5, 8):
            req = self._request(number[-keep:])
            self.assertFalse(
                req.phone_matches_spent_student,
                "%r matched - too few digits to identify anyone"
                % number[-keep:])

    # -- 5. a number two people share ----------------------------------------

    def test_a_shared_number_is_reported_once_and_names_one(self):
        number = self._free_number()
        self._student("share_a", number)
        self._student("share_b", number)
        req = self._request(number)
        self.assertTrue(req.phone_matches_spent_student)
        warning = req.phone_match_warning or ""
        self.assertTrue(warning, "no warning on a shared number")
        self.assertFalse(
            "Phone share_a" in warning and "Phone share_b" in warning,
            "a shared number read out a list of everyone on it; one name is "
            "enough to make the call")

    # -- it keeps out of the other flag's way --------------------------------

    def test_it_stays_quiet_when_the_email_already_identifies_her(self):
        """Trial Used already says so; a second badge is noise."""
        number = self._free_number()
        partner = self._student("known", number)
        req = self.TR.create({
            "name": partner.name, "email": partner.email,
            "phone": number, "class_interest": "reformer",
            "status": "pending", "lang": "en_US",
        })
        self.env.invalidate_all()
        self.assertTrue(
            req.trial_already_used,
            "the email flag should have caught this one")
        self.assertFalse(
            req.phone_matches_spent_student,
            "both flags fired for the same person")

    def test_a_finished_request_carries_neither_flag(self):
        number = self._free_number()
        self._student("closed", number)
        for status in ("scheduled", "declined"):
            req = self._request(number, status=status)
            self.assertFalse(
                req.phone_matches_spent_student,
                "a %s request was flagged - the studio has already dealt "
                "with it" % status)

    # -- 7. approval is untouched --------------------------------------------

    def test_approval_behaves_exactly_as_before(self):
        """A warning must not become a rule. A phone-matched request from
        somebody with her own entitlement intact is still approvable."""
        number = self._free_number()
        self._student("appr_other", number)
        newcomer = self.env["res.partner"].create({
            "name": "Phone Newcomer",
            "email": "phone.newcomer@example.invalid",
            "phone": number,
        })
        req = self._request(number, email=newcomer.email)
        self.env.invalidate_all()
        self.assertTrue(
            req.phone_matches_spent_student,
            "fixture wrong: this request should be phone-matched")
        self.assertFalse(
            req.trial_already_used,
            "she has her own entitlement - approval must not refuse her")

    def test_the_two_flags_are_separate_columns_with_separate_words(self):
        """If they shared wording the studio would stop trusting either."""
        number = self._free_number()
        self._student("wording", number)
        req = self._request(number)
        self.assertTrue(req.phone_matches_spent_student)
        self.assertNotEqual(
            req.phone_match_warning, req.trial_used_warning,
            "the guess and the certainty say the same thing")
        self.assertIn(
            "phone", (req.phone_match_warning or "").lower(),
            "the warning does not say what it is based on")


@tagged("post_install", "-at_install")
class TestPhoneMatchTellsTheVisitorNothing(PhoneMatchFixture, HttpCase):
    """6. The response must be identical whether the number matches or not.

    Asserted on what comes back over HTTP, not on the database. A public
    visitor learning that a number is known here is the leak this whole
    design avoids.
    """

    longMessage = False

    def setUp(self):
        super().setUp()
        self._build()
        self._ensure_slot()

    def _ensure_slot(self):
        """Put one bookable group class on the calendar.

        Without this the whole class skips on a fresh database - and a skip
        proves nothing. The privacy assertion is the reason this feature is
        shaped the way it is, so it has to run on both shapes rather than
        only on the restore that happens to have a timetable.
        """
        ctype = self.env["fitness.class.type"].sudo().create({
            "name": "Phone Match Reformer",
            "classroom_type": "reformer",
            "duration": 50,
            "level": "all",
            "session_type": "group",
        })
        start = fields.Datetime.now() + timedelta(days=3)
        self.slot_event = self.env["calendar.event"].sudo().create({
            "name": "Phone Match class",
            "start": start,
            "stop": start + timedelta(minutes=50),
            "class_type_id": ctype.id,
            "is_fitness_class": True,
            "capacity": 10,
        })
        self.env.flush_all()

    def _find_slot(self):
        for n in range(2, 21):
            day = (date.today() + timedelta(days=n)).isoformat()
            for period in ("morning", "evening"):
                res = self.url_open(
                    "/trial/classes?date=%s&period=%s" % (day, period))
                try:
                    slots = res.json().get("slots", [])
                except Exception:
                    slots = []
                if slots:
                    return day, period, slots[0]
        return None

    def _submit(self, phone, email):
        found = self._find_slot()
        self.assertTrue(
            found,
            "no slot was offered even though one was put on the calendar - this test must not quietly skip, it is the privacy assertion")
        day, period, slot = found
        page = self.url_open("/trial")
        tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text)
        return self.url_open("/trial/submit", data={
            "csrf_token": tok.group(1) if tok else "",
            "name": "Public Visitor", "email": email, "phone": phone,
            "class_interest": slot["discipline"],
            "class_type_id": str(slot["class_type_id"]),
            "occurrence_id": str(slot["id"]),
            "preferred_date": day, "preferred_period": period,
            "reformer_is_first_time": "yes", "source": "website",
        })

    def test_the_visitor_cannot_tell_a_match_from_a_non_match(self):
        number = self._free_number()
        self._student("http_spent", number)

        matched = self._submit(number, "v.match@example.invalid")
        plain = self._submit(self._free_number(), "v.plain@example.invalid")

        self.assertEqual(
            matched.status_code, plain.status_code,
            "a matched number answers with a different status")
        for marker in ("already used", "ya ha usado", "ja ha fet servir",
                       "Phone http_spent"):
            self.assertNotIn(
                marker, matched.text,
                "the page told the visitor about the match (%r)" % marker)

    def test_the_studio_sees_it_even_though_the_visitor_does_not(self):
        """The other half: silent to her must not mean silent to everyone."""
        number = self._free_number()
        self._student("http_seen", number)
        self._submit(number, "v.seen@example.invalid")

        req = self.TR.search(
            [("email", "=ilike", "v.seen@example.invalid")], limit=1)
        self.assertTrue(req, "the request was not recorded at all")
        self.assertTrue(
            req.phone_matches_spent_student,
            "the studio has no way to see this may be the same person")
