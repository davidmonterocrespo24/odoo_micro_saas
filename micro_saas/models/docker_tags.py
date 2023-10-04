from random import randint

from odoo import fields, models


class Tag(models.Model):
    _name = "docker.compose.tag"
    _description = "Docker compose Tag"

    def _get_default_color(self):
        return randint(1, 11)

    name = fields.Char('Tag Name', required=True, translate=True)
    color = fields.Integer('Color', default=_get_default_color)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', "Tag name already exists !"),
    ]
