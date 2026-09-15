# -*- coding: utf-8 -*-
"""The portal shows studio time, whatever the account's timezone says.

The bug these cover shipped to production and was reported from a phone in
India: a class at 07:00 Madrid read "10:30" on My Schedule while the very same
class read "07:00" on the booking page one tap away.

The two halves of the page disagreed because they asked different things for
the timezone. Everything the controller formats in Python goes through
_user_tz(), which was pinned to Europe/Madrid. The class time on the card was
not formatted in the controller at all - it was a bare

    <span t-field="booking.class_start"
          t-options='{"widget":"datetime","format":"HH:mm"}'/>

and t-field renders through ir.qweb.field.datetime, which converts using
self.env.context['tz'] - the account's timezone, straight out of
res.users.context_get(). The pin never touched it. Passing tz_name in
t-options is what makes the converter use the studio's clock instead.

So the account here is deliberately set to Asia/Calcutta: it reproduces the
reporter's machine, and every assertion below fails on the pre-fix template.
"""
import re
from datetime import datetime, timedelta

import pytz

from odoo import fields
from odoo.tests import HttpCase, tagged

STUDIO_TZ = pytz.timezone('Europe/Madrid')
WRONG_TZ = pytz.timezone('Asia/Calcutta')


def _text(html):
    """Visible text, so a failure names its own cause instead of dumping HTML."""
    html = re.sub(r'(?s)<(script|style).*?</\1>', ' ', html)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()


@tagged("post_install", "-at_install")
class TestPortalRendersStudioTime(HttpCase):

    longMessage = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'fitness.trial_offer_end', '2000-01-01')

        cls.password = "tz-test-pw-1"
        cls.user = cls.env["res.users"].create({
            "name": "Timezone Test Student",
            "login": "tz.student@example.invalid",
            "password": cls.password,
            "lang": "en_US",
            # The whole point. If the portal ever reads this again, every
            # assertion below turns red.
            "tz": "Asia/Calcutta",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_portal").id,
                cls.env.ref("fitness_core.group_fitness_student").id,
            ])],
        })
        cls.partner = cls.user.partner_id

        cls.class_type = cls.env["fitness.class.type"].create({
            "name": "Timezone Test Reformer",
            "classroom_type": "reformer",
            "duration": 45,
            "level": "all",
            "session_type": "group",
        })
        cls.product = cls.env["product.product"].create({
            "name": "Timezone Test Pack",
            "list_price": 50.0,
            "sale_ok": True,
            "type": "service",
            "fitness_is_package": True,
            "fitness_class_type": "reformer",
        })
        cls.order = cls.env["sale.order"].create({"partner_id": cls.partner.id})
        cls.line = cls.env["sale.order.line"].create({
            "order_id": cls.order.id,
            "product_id": cls.product.id,
            "product_uom_qty": 4,
            "fitness_original_class_count": 4,
            "fitness_remaining_classes": 4,
            "fitness_validity_end_date": fields.Date.today() + timedelta(days=60),
        })

    @classmethod
    def _at_studio_hour(cls, day_offset, hour):
        """A naive UTC datetime for `hour` o'clock studio time, `day_offset` away.

        Built from the studio zone rather than by subtracting a fixed offset,
        so the test keeps working across the DST change that would otherwise
        make it fail for one week in spring and one in autumn.
        """
        day = (datetime.utcnow() + timedelta(days=day_offset)).date()
        local = STUDIO_TZ.localize(datetime(day.year, day.month, day.day, hour, 0))
        return local.astimezone(pytz.UTC).replace(tzinfo=None), local

    @classmethod
    def _expectations(cls, local):
        """(what the studio clock says, what the account's wrong clock says)."""
        utc = local.astimezone(pytz.UTC)
        return (local.strftime('%H:%M'),
                utc.astimezone(WRONG_TZ).strftime('%H:%M'))

    def _book(self, day_offset, hour, name):
        start, local = self._at_studio_hour(day_offset, hour)
        event = self.env["calendar.event"].create({
            "name": name,
            "start": start,
            "stop": start + timedelta(minutes=45),
            "class_type_id": self.class_type.id,
            # students' calendar.event rule is [('is_fitness_class','=',True)];
            # without it the portal answers 403 and every assertion below
            # would fail for an unrelated reason
            "is_fitness_class": True,
        })
        booking = self.env["fitness.booking"].create({
            "student_id": self.partner.id,
            "calendar_event_id": event.id,
            "state": "booked",
            "package_order_line_id": self.line.id,
        })
        return booking, event, local

    def _page(self, url):
        self.env.flush_all()
        self.authenticate(self.user.login, self.password)
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200,
                         "%s did not load: %s" % (url, _text(res.text)[:700]))
        return res.text

    def _assert_studio_time(self, label, html, event_name, studio, wrong):
        self.assertIn(event_name, html,
                      "%s did not render the class at all - the timezone "
                      "assertions would pass for the wrong reason" % label)
        self.assertIn(studio, html,
                      "%s does not show the studio time %s" % (label, studio))
        self.assertNotIn(wrong, html,
                         "%s shows %s - the account's Asia/Calcutta clock, not "
                         "the studio's" % (label, wrong))

    def test_my_schedule_shows_studio_time(self):
        """The screen from the bug report: booked class, 07:00 not 10:30."""
        booking, event, local = self._book(2, 7, "TZ Schedule Class")
        studio, wrong = self._expectations(local)
        self.assertNotEqual(studio, wrong, "test is meaningless if both agree")
        html = self._page("/my/studio?view=schedule")
        self._assert_studio_time("My Schedule", html, event.name, studio, wrong)

    def test_home_next_class_shows_studio_time(self):
        """Home renders the same booking through its own template."""
        booking, event, local = self._book(2, 7, "TZ Home Class")
        studio, wrong = self._expectations(local)
        html = self._page("/my/home")
        self._assert_studio_time("Home", html, event.name, studio, wrong)

    def test_history_shows_studio_time(self):
        """Past classes, the third template rendering class_start."""
        booking, event, local = self._book(2, 7, "TZ History Class")
        # Booking validation refuses a class in the past, which is correct and
        # is why the class is booked in the future and then moved back. What
        # History renders is class_start, a stored related field, so it follows.
        past_start, past_local = self._at_studio_hour(-3, 7)
        event.write({"start": past_start,
                     "stop": past_start + timedelta(minutes=45)})
        studio, wrong = self._expectations(past_local)
        html = self._page("/my/history")
        self._assert_studio_time("My History", html, event.name, studio, wrong)

    def test_no_view_renders_a_class_time_without_a_timezone(self):
        """A guard for templates these tests do not fetch.

        The three pages above are the ones that were wrong, but the defect is
        a property of the markup, not of those pages: any new
        t-field="...class_start" inherits the account's timezone unless it says
        otherwise. This reads the arch as loaded in the database, so it also
        covers views from other modules and any future inheritance.
        """
        views = self.env["ir.ui.view"].search([
            ("type", "=", "qweb"), ("arch_db", "like", "class_start"),
        ])
        offenders = []
        for view in views:
            for tag in re.findall(r'<[^>]*t-field="[^"]*class_start"[^>]*>',
                                  view.arch or ''):
                if 'tz_name' not in tag:
                    offenders.append("%s: %s" % (view.xml_id or view.name,
                                                 ' '.join(tag.split())[:120]))
        self.assertFalse(
            offenders,
            "these render a class time on the reader's own clock instead of "
            "the studio's - add the tz_name option to t-options:\n  "
            + "\n  ".join(offenders))
