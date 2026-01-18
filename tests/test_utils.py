from akaidoo.utils import get_model_relations


def test_get_model_relations():
    code = """
from odoo import models, fields

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    partner_id = fields.Many2one('res.partner', string='Customer')
    line_ids = fields.One2many('sale.order.line', 'order_id')
    tag_ids = fields.Many2many('crm.tag')

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    product_id = fields.Many2one('product.product')

class AbstractMixin(models.AbstractModel):
    _name = 'my.mixin'

    name = fields.Char()

class Delegation(models.Model):
    _name = 'delegated.model'
    _inherits = {'parent.model': 'parent_id'}
"""
    relations = get_model_relations(code)

    assert "sale.order" in relations
    assert relations["sale.order"]["parents"] == {"mail.thread", "mail.activity.mixin"}
    assert relations["sale.order"]["comodels"] == {
        "res.partner",
        "sale.order.line",
        "crm.tag",
    }
    assert "sale.order.line" in relations
    assert not relations["sale.order.line"]["parents"]
    assert relations["sale.order.line"]["comodels"] == {"product.product"}
    assert "my.mixin" in relations  # Abstract models should be picked up
    assert "delegated.model" in relations
    assert relations["delegated.model"]["parents"] == {"parent.model"}
