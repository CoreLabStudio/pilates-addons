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
    body_excerpt = fields.Char(compute='_compute_body_excerpt')

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
