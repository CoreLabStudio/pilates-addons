from odoo import models, fields, api
import re


class FitnessNewsPost(models.Model):
    _name = 'fitness.news.post'
    _description = 'News Post / Promotion'
    _order = 'sequence asc, publish_date desc, id desc'
    # The title, not "name". Without this Odoo looks for a field called name,
    # finds none, and falls back to printing the model and id - so the
    # breadcrumb over an open post read "fitness.news.post,1", and so did every
    # other place a record refers to itself.
    _rec_name = 'title'

    title = fields.Char("Title", required=True, translate=True)
    body = fields.Html("Body", sanitize=True, translate=True)
    image = fields.Image("Image", max_width=1600, max_height=900)
    active = fields.Boolean(default=True)
    publish_date = fields.Date(
        "Publish Date",
        required=True,
        default=fields.Date.today,
    )
    sequence = fields.Integer("Sequence", default=10)
    cta_url = fields.Char(
        "Call-to-action link",
        help="Optional. When set, the post's detail page shows a button "
             "linking here - e.g. /my/studio to send readers to the class "
             "timetable. Leave empty for a post that is just an announcement.",
    )
    cta_label = fields.Char(
        "Call-to-action label",
        translate=True,
        help="Text on that button. Falls back to a generic label when empty.",
    )
    body_excerpt = fields.Char(compute='_compute_body_excerpt')

    # ── the call-to-action link ──────────────────────────────────────────────
    #
    # Anyone writing a link types "corelabstudio.es". A browser reads that as a
    # path, not a host, so the button landed on
    # app.corelabstudio.es/my/news/<id>/corelabstudio.es - a 404 - while the
    # admin form showed exactly what had been typed and said nothing was wrong.
    #
    # Normalised on the way in rather than on the way out, so the stored value
    # is the one that works and the form shows the studio what the button will
    # actually do.
    _URL_SCHEMES = ('http://', 'https://', 'mailto:', 'tel:')

    @api.model
    def _normalise_cta_url(self, url):
        if not url:
            return url
        url = url.strip()
        if not url:
            return False
        low = url.lower()
        # Already absolute, or deliberately internal - both already work.
        if low.startswith(self._URL_SCHEMES) or url.startswith('/'):
            return url
        # Anything else is a bare host or host/path: make it absolute.
        return 'https://' + url.lstrip('/')

    @api.onchange('cta_url')
    def _onchange_cta_url(self):
        """Show the studio the corrected link while they are still editing."""
        for rec in self:
            rec.cta_url = rec._normalise_cta_url(rec.cta_url)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('cta_url'):
                vals['cta_url'] = self._normalise_cta_url(vals['cta_url'])
        return super().create(vals_list)

    def write(self, vals):
        # The onchange only fires in the form. Imports, the shell and any other
        # write path reach here instead, and a link that 404s is no better for
        # arriving by a different door.
        if vals.get('cta_url'):
            vals['cta_url'] = self._normalise_cta_url(vals['cta_url'])
        return super().write(vals)

    @api.depends('body')
    def _compute_body_excerpt(self):
        _tag = re.compile(r'<[^>]+>')
        _ent = re.compile(r'&[a-z#0-9]+;')
        for post in self:
            raw = post.body or ''
            text = _tag.sub('', raw)
            text = _ent.sub(' ', text)
            text = ' '.join(text.split())
            if len(text) > 120:
                text = text[:120].rsplit(' ', 1)[0] + '…'
            post.body_excerpt = text
