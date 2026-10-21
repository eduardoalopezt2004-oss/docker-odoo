from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        res = super()._action_done()
        # Solo encola el aviso; el envío lo hace el cron para no frenar a quien valida.
        self.env["shop.webhook.event"]._queue_deliveries(self)
        return res
