from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    shop_webhook_url = fields.Char(
        string="URL del aviso de entrega",
        config_parameter="shop_integration_api.webhook_url",
    )
    shop_webhook_secret = fields.Char(
        string="Secreto para firmar el aviso",
        config_parameter="shop_integration_api.webhook_secret",
    )
