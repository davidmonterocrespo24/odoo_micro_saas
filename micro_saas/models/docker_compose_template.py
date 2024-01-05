import logging
import re
from functools import reduce

from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


# Docker Compose Template Autor David Montero Crespo
class DockerComposeTemplate(models.Model):
    _name = 'docker.compose.template'
    _description = 'Docker Compose Template'
    _order = 'sequence asc, id'

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'The name of the template must be unique !'),
    ]

    def _default_template_odoo_conf(self):
        odoo_conf_content = "[options]\naddons_path =/mnt/extra-addons/ \n"
        odoo_conf_content += "admin_passwd = admin\n"
        odoo_conf_content += "data_dir = /var/lib/odoo\n"
        odoo_conf_content += "logfile = /var/log/odoo/odoo.log\n"
        return odoo_conf_content

    name = fields.Char(string="Name", required=True)
    sequence = fields.Integer(required=True, default=0)
    active = fields.Boolean(default=True)
    variable_ids = fields.One2many('docker.compose.template.variable', 'dc_template_id',
                                   string="Template Variables", store=True, compute='_compute_variable_ids',
                                   precompute=True, readonly=False)
    result_dc_body = fields.Text(string="Result Docker Compose", compute='_compute_result_dc_body', store=True)
    tag_ids = fields.Many2many('docker.compose.tag', string="Tags", tracking=True)
    template_dc_body = fields.Text(string="Template Docker Compose")
    repository_line = fields.One2many('repository.repo.line', 'instance_id', string='Repository and Branch')
    result_odoo_conf = fields.Text(string="Result Odoo Conf", compute='_compute_result_odoo_conf', store=True)
    template_odoo_conf = fields.Text(string="Template Odoo Conf", default=_default_template_odoo_conf)
    template_postgres_conf = fields.Text(string="Template Postgres Conf")
    result_postgres_conf = fields.Text(string="Result Postgres Conf", compute='_compute_result_postgres_conf',
                                       store=True)
    is_result_odoo_conf = fields.Boolean(string="Result Odoo Conf")
    is_result_postgres_conf = fields.Boolean(string="Result Postgres Conf")
    is_result_dc_body = fields.Boolean(string="Result Docker Compose")

    @api.depends('template_dc_body', 'template_odoo_conf', 'template_postgres_conf')
    def _compute_variable_ids(self):
        """compute template variable according to header text, body and buttons"""
        for tmpl in self:
            to_delete = []
            to_create = []
            body_variables = set(re.findall(r'{{[^{}]+}}', tmpl.template_dc_body or ''))
            # sumar las variables de template_odoo_conf
            body_variables = body_variables.union(set(re.findall(r'{{[^{}]+}}', tmpl.template_odoo_conf or '')))
            # sumar las variables de template_postgres_conf
            body_variables = body_variables.union(set(re.findall(r'{{[^{}]+}}', tmpl.template_postgres_conf or '')))
            existing_body_variables = tmpl.variable_ids
            existing_body_variables = {var.name: var for var in existing_body_variables}
            new_body_variable_names = [var_name for var_name in body_variables if
                                       var_name not in existing_body_variables]
            deleted_body_variables = [var.id for name, var in existing_body_variables.items() if
                                      name not in body_variables]

            to_create += [{'name': var_name} for var_name in set(new_body_variable_names)]
            to_delete += deleted_body_variables

            update_commands = [Command.delete(to_delete_id) for to_delete_id in to_delete] + [Command.create(vals) for
                                                                                              vals in to_create]
            if update_commands:
                tmpl.variable_ids = update_commands

    @api.depends('template_dc_body', 'variable_ids', 'is_result_dc_body')
    @api.onchange('template_dc_body', 'variable_ids', 'is_result_dc_body')
    def _compute_result_dc_body(self):
        for template in self:
            template.result_dc_body = template._get_formatted_body(template_body=template.template_dc_body,
                                                                   demo_fallback=True)

    @api.depends('template_odoo_conf', 'variable_ids', 'is_result_odoo_conf')
    @api.onchange('template_odoo_conf', 'variable_ids', 'is_result_odoo_conf')
    def _compute_result_odoo_conf(self):
        for template in self:
            template.result_odoo_conf = template._get_formatted_body(template_body=template.template_odoo_conf,
                                                                     demo_fallback=True)

    @api.depends('template_postgres_conf', 'variable_ids', 'is_result_postgres_conf')
    @api.onchange('template_postgres_conf', 'variable_ids', 'is_result_postgres_conf')
    def _compute_result_postgres_conf(self):
        for template in self:
            template.result_postgres_conf = template._get_formatted_body(template_body=template.template_postgres_conf,
                                                                         demo_fallback=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.variable_ids._check_field_name()
        return records

    def write(self, vals):
        res = super().write(vals)
        self.variable_ids._check_field_name()
        return res

    def copy(self, default=None):
        self.ensure_one()
        default = default or {}
        if not default.get('name'):
            default['name'] = _('%(original_name)s (copy)', original_name=self.name)
        return super().copy(default)

    def _get_formatted_body(self, template_body='', demo_fallback=False, variable_values=None):
        self.ensure_one()
        result_body = template_body or ''
        for var in self.variable_ids:
            fallback_value = var.demo_value if demo_fallback else ' '
            _logger.info(f"++++ var.name: ***{var.name}****")
            result_body = result_body.replace(var.name, fallback_value)
        return result_body

    def create_instance_from_template(self):
        self.ensure_one()

        return {
            'name': _('Create Instance'),
            'type': 'ir.actions.act_window',
            'res_model': 'odoo.docker.instance',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_name': self.name + " from Template",
                'default_template_id': self.id,
            }
        }


class DockerComposeTemplateVariable(models.Model):
    _name = 'docker.compose.template.variable'
    _description = 'Docker Compose Template Variable'

    name = fields.Char(string="Placeholder", required=True)
    dc_template_id = fields.Many2one(comodel_name='docker.compose.template', ondelete='cascade')
    field_type = fields.Selection([
        ('free_text', 'Free Text'),
        ('field', 'Field of Model')], string="Type", default='free_text', required=True)
    field_name = fields.Char(string="Field")
    demo_value = fields.Char(string="Sample Value", default="Sample Value", required=True)
    instance_id = fields.Many2one('odoo.docker.instance', string='Instance', ondelete='cascade')
    _sql_constraints = [
        (
            'name_type_template_unique',
            'UNIQUE(name, dc_template_id,instance_id)',
            'Variable names must be unique for a given template'
        ),
    ]

    @api.constrains('field_type', 'demo_value')
    def _check_demo_values(self):
        if self.filtered(lambda var: var.field_type == 'free_text' and not var.demo_value):
            raise ValidationError(_('Free Text template variables must have a demo value.'))
        if self.filtered(lambda var: var.field_type == 'field' and not var.field_name):
            raise ValidationError(_("Field template variables must be associated with a field."))

    @api.constrains('field_name')
    def _check_field_name(self):
        for variable in self:
            if not variable.field_name or self.user_has_groups('base.group_system'):
                continue

            model = self.env[variable.model]
            if not model.check_access_rights('read', raise_exception=False):
                raise ValidationError(_("You can not select field of %r.", variable.model))

            if variable.field_name not in model:
                raise ValidationError(_("Invalid field name: %r", variable.field_name))


def _get_variables_value(self, record):
    value_by_name = {}
    for variable in self:
        if variable.field_type == 'field':
            value = variable._find_value_from_field_chain(record)
        else:
            value = variable.demo_value

        value_str = value and str(value) or ''
        value_by_name[variable.name] = value_str

    return value_by_name


def _find_value_from_field_chain(self, record):
    """Get the value of field, returning display_name(s) if the field is a model."""
    self.ensure_one()
    if len(record) != 1:
        raise UserError(_('Fetching field value for template variable must use a single record'))
    if not self.field_type == 'field':
        raise UserError(
            _('Cannot get field value from %(variable_type)s template variable', variable_type=self.field_type))

    try:
        field_value = reduce(lambda record, field: record[field], self.field_name.split('.'), record.sudo(False))
    except KeyError:
        raise UserError(_("Invalid field chain %r", self.field_name))
    except Exception:
        raise UserError(_("Not able to get the value of field %r", self.field_name))
    if isinstance(field_value, models.Model):
        return ' '.join(value.display_name for value in field_value)
    return field_value


def _extract_variable_index(self):
    """ Extract variable index, located between '{{}}' markers. """
    self.ensure_one()
    try:
        return int(self.name.lstrip('{{').rstrip('}}'))
    except ValueError:
        return None
