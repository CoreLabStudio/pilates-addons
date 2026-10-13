# -*- coding: utf-8 -*-
"""Excel for the Free classes given list, and for nothing else.

WHY THIS EXISTS AT ALL, instead of Odoo's own Export button. Export is
gated on base.group_allow_export, which on this database is implied by
group_system alone - so a fitness manager cannot export anything, from
any screen. Putting her in that group would let her export every model
she can read, which is a far bigger change than one list needing a
spreadsheet, and this change is not allowed to widen anything beyond
managers.

So: one route, for one model. The ids arrive in the query string and are
read back THROUGH THE ORM AS THE PERSON WHO ASKED, so
fitness.free.credit.report's own access row is what decides what comes
out. A student or an instructor has no row on that model, so there is
nothing an id in a URL can fish out of here - the read raises before a
single cell is written. The group is checked first as well, so the
answer to somebody who should not be here is 403 rather than an empty
spreadsheet.
"""
import io
import logging

import pytz

from odoo import http, models, _
from odoo.http import request

from odoo.addons.fitness_core.models.studio_time import studio_tz

_logger = logging.getLogger(__name__)

MANAGER_GROUP = 'fitness_core.group_fitness_manager'
MODEL = 'fitness.free.credit.report'

# Column order, and the field behind each one. The same order the list
# shows, so a manager who exports what she is looking at gets what she
# was looking at.
COLUMNS = (
    ('Given', 'given_on'),
    ('Month', 'given_month'),
    ('Student', 'student_id'),
    ('Product', 'product_id'),
    ('What', 'given_type'),
    ('Discipline', 'discipline'),
    ('Session', 'session_type'),
    ('Given by', 'given_by'),
    ('Reason', 'reason'),
    ('Status', 'status'),
    ('Expires on', 'expires_on'),
    ('Classes given', 'credits_given'),
    ('Classes left', 'credits_left'),
    ('Class it paid for', 'used_event_id'),
    ('Value', 'value_given'),
    ('Order', 'order_id'),
)


class FitnessFreeCreditsExport(http.Controller):

    @http.route('/fitness/free_credits/export.xlsx', type='http',
                auth='user', methods=['GET'], csrf=False)
    def export_xlsx(self, ids=None, **kw):
        if not request.env.user.has_group(MANAGER_GROUP):
            _logger.warning(
                "[FREE CREDITS] %s asked for the export and is not a "
                "manager", request.env.user.login)
            raise request.not_found()

        Report = request.env[MODEL]
        # As the user, never sudo. The access row is the rule, and an id
        # in a URL is not a reason to bypass it.
        if ids:
            wanted = [int(i) for i in str(ids).split(',') if i.strip()]
            rows = Report.browse(wanted).exists()
        else:
            rows = Report.search([])

        try:
            import xlsxwriter
        except ImportError:
            # Odoo ships xlsxwriter, so this is a broken environment and
            # not a case to design for - but a traceback in the browser
            # is no use to the owner.
            _logger.exception("[FREE CREDITS] xlsxwriter is not available")
            raise

        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True,
                                            'remove_timezone': True})
        head = book.add_format({'bold': True, 'bg_color': '#EEEEEE',
                                'border': 1})
        date_fmt = book.add_format({'num_format': 'yyyy-mm-dd hh:mm'})
        day_fmt = book.add_format({'num_format': 'yyyy-mm-dd'})
        money = book.add_format({'num_format': '#,##0.00'})

        sheet = book.add_worksheet(_("Free classes given")[:31])
        sheet.freeze_panes(1, 0)
        for col, (label, _field) in enumerate(COLUMNS):
            # The header in the reader's own language, like every other
            # label she sees. request.env._ is the user's.
            sheet.write(0, col, request.env._(label), head)

        # Selection labels, in the reader's language, resolved once.
        selections = {}
        for name in ('given_type', 'discipline', 'session_type', 'status'):
            selections[name] = dict(
                Report.fields_get([name])[name]['selection'])

        for row_no, row in enumerate(rows, start=1):
            for col, (_label, name) in enumerate(COLUMNS):
                value = row[name]
                if name in selections:
                    sheet.write(row_no, col,
                                selections[name].get(value, value or ''))
                elif name == 'given_on':
                    # Madrid wall-clock time, as the list shows it; the
                    # stored value is naive UTC.
                    local = (pytz.utc.localize(value).astimezone(
                        studio_tz()).replace(tzinfo=None) if value else None)
                    if local:
                        sheet.write_datetime(row_no, col, local, date_fmt)
                    else:
                        sheet.write(row_no, col, '')
                elif name == 'expires_on':
                    sheet.write_datetime(row_no, col, value, day_fmt) \
                        if value else sheet.write(row_no, col, '')
                elif name == 'value_given':
                    sheet.write_number(row_no, col, value or 0.0, money)
                elif name in ('credits_given', 'credits_left'):
                    sheet.write_number(row_no, col, int(value or 0))
                elif isinstance(value, models.BaseModel):
                    # The NAME only, read as superuser: the same name the
                    # list and form already show her for this row (the web
                    # client reads a many2one's display name that way).
                    # Reading it as her raised on the order, which she has
                    # no right to open - and still has none: nothing here
                    # reads the order itself.
                    sheet.write(row_no, col,
                                value.sudo().display_name or '')
                else:
                    sheet.write(row_no, col, value or '')

        for col, (label, _f) in enumerate(COLUMNS):
            sheet.set_column(col, col, max(12, len(label) + 4))
        book.close()
        payload = stream.getvalue()
        stream.close()

        _logger.info("[FREE CREDITS] %s exported %d row(s)",
                     request.env.user.login, len(rows))
        return request.make_response(payload, headers=[
            ('Content-Type',
             'application/vnd.openxmlformats-officedocument'
             '.spreadsheetml.sheet'),
            ('Content-Disposition',
             'attachment; filename="free-classes-given.xlsx"'),
            ('Content-Length', str(len(payload))),
        ])
