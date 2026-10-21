import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.shop_integration_api.models.shop_webhook_event import RETRY_MINUTES

POST = "odoo.addons.shop_integration_api.models.shop_webhook_event.requests.post"
URL = "https://tienda.example.com/odoo/avisos"
SECRET = "clave-de-prueba-no-real"


def _response(status):
    response = MagicMock()
    response.status_code = status
    return response


@tagged("post_install", "-at_install")
class TestDeliveryWebhook(TransactionCase):
    """Tramo C: aviso a la tienda al validar la entrega de un pedido creado por la API."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("shop_integration_api.webhook_url", URL)
        params.set_param("shop_integration_api.webhook_secret", SECRET)
        cls.customer = cls.env["res.partner"].create({"name": "Cliente avisos"})
        cls.product = cls.env["product.product"].create(
            {"name": "Silla avisos", "default_code": "AVISO-001", "is_storable": True, "list_price": 40.0}
        )
        cls.env["stock.quant"]._update_available_quantity(cls.product, cls.env.ref("stock.stock_location_stock"), 100)
        cls.warehouse_user = new_test_user(cls.env, login="shop_warehouse_user", groups="base.group_user,stock.group_stock_user")
        cls.cron = cls.env.ref("shop_integration_api.ir_cron_send_shop_webhooks")

    def _order(self, quantity=10, api=True, ref="WEB-AVISO-1"):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "client_order_ref": ref,
                "shop_api_order": api,
                "order_line": [Command.create({"product_id": self.product.id, "product_uom_qty": quantity})],
            }
        )
        order.action_confirm()
        return order

    def _deliver(self, picking, quantity, user=None, cancel_backorder=False):
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = quantity
            move.picked = True
        # cancel_backorder=True: validar una entrega parcial sin crear entrega pendiente (lo que falta se cancela).
        picking.with_user(user or self.env.user).with_context(cancel_backorder=cancel_backorder)._action_done()

    def _events(self, order):
        return self.env["shop.webhook.event"].search([("order_id", "=", order.id)], order="id")

    def _send_due(self):
        self.env["shop.webhook.event"]._cron_send_pending()

    def test_validating_the_delivery_queues_a_notice_without_calling_the_store(self):
        order = self._order()
        with patch(POST) as post:
            self._deliver(order.picking_ids, 10, self.warehouse_user)
        post.assert_not_called()
        event = self._events(order)
        self.assertEqual(len(event), 1)
        self.assertEqual((event.state, event.attempts, event.event_type), ("pending", 0, "order.delivered"))
        self.assertTrue(self.env["ir.cron.trigger"].search([("cron_id", "=", self.cron.id)]), "El envío se programa enseguida")

    def test_store_down_does_not_block_whoever_validates(self):
        order = self._order()
        with patch(POST, side_effect=requests.ConnectionError("tienda caída")) as post:
            self._deliver(order.picking_ids, 10, self.warehouse_user)
            self.assertEqual(order.picking_ids.state, "done")
            post.assert_not_called()
            before = fields.Datetime.now()
            self._send_due()
        event = self._events(order)
        self.assertEqual((event.state, event.attempts), ("pending", 1))
        self.assertIn("tienda caída", event.last_error)
        self.assertGreaterEqual(event.next_attempt, before + timedelta(minutes=RETRY_MINUTES[0]) - timedelta(seconds=5))

    def test_payload(self):
        order = self._order()
        self._deliver(order.picking_ids, 10)
        event = self._events(order)
        payload = json.loads(event.payload)
        self.assertEqual(payload["event"], "order.delivered")
        self.assertEqual(payload["event_id"], event.event_uuid)
        self.assertEqual(payload["order"], {"id": order.id, "name": order.name, "external_ref": "WEB-AVISO-1"})
        self.assertEqual(payload["delivery"]["name"], order.picking_ids.name)
        self.assertEqual(payload["delivery"]["lines"], [{"product_id": self.product.id, "default_code": "AVISO-001", "quantity": 10.0}])
        self.assertTrue(payload["fully_delivered"])
        # Nada sensible: sin precios ni datos del cliente.
        self.assertNotIn("Cliente avisos", event.payload)

    def test_successful_send_is_signed_and_marked_sent(self):
        order = self._order()
        self._deliver(order.picking_ids, 10)
        event = self._events(order)
        with patch(POST, return_value=_response(200)) as post:
            self._send_due()
        self.assertEqual((event.state, event.attempts, event.last_status), ("sent", 1, 200))
        args, kwargs = post.call_args
        self.assertEqual(args[0], URL)
        body = kwargs["data"]
        self.assertEqual(body, event.payload.encode())
        headers = kwargs["headers"]
        self.assertEqual(headers["X-Shop-Event-Id"], event.event_uuid)
        expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertEqual(headers["X-Shop-Signature"], expected)
        self.assertTrue(kwargs["timeout"])
        # Sin descargar el cuerpo de la respuesta (Odoo no lo usa): uno grande o lento no retiene el cron.
        self.assertTrue(kwargs.get("stream"))
        post.return_value.close.assert_called_once()

    def test_any_non_2xx_is_retried_on_schedule_until_failed(self):
        order = self._order()
        self._deliver(order.picking_ids, 10)
        event = self._events(order)
        for attempt, status in enumerate([500, 400, 404, 503, 500, 500, 500, 500], start=1):
            with self.subTest(attempt=attempt), patch(POST, return_value=_response(status)):
                self._send_due()
                self.assertEqual((event.state, event.attempts, event.last_status), ("pending", attempt, status))
                self.assertEqual(event.next_attempt - event.last_attempt, timedelta(minutes=RETRY_MINUTES[attempt - 1]))
                # Antes de la hora programada no se reintenta.
                self._send_due()
                self.assertEqual(event.attempts, attempt)
                event.sudo().next_attempt = fields.Datetime.now() - timedelta(seconds=1)
        with patch(POST, return_value=_response(500)):
            self._send_due()
        self.assertEqual((event.state, event.attempts), ("failed", len(RETRY_MINUTES) + 1))

    def test_manual_retry_of_a_failed_notice(self):
        order = self._order()
        self._deliver(order.picking_ids, 10)
        event = self._events(order)
        event.sudo().write({"state": "failed", "attempts": len(RETRY_MINUTES) + 1})
        event.action_retry()
        self.assertEqual(event.state, "pending")
        self.assertLessEqual(event.next_attempt, fields.Datetime.now())
        with patch(POST, return_value=_response(200)):
            self._send_due()
        self.assertEqual(event.state, "sent")

    def test_each_partial_delivery_notifies(self):
        order = self._order(quantity=10)
        first_picking = order.picking_ids
        self._deliver(first_picking, 6)
        backorder = order.picking_ids - first_picking
        self.assertTrue(backorder)
        self._deliver(backorder, 4)
        events = self._events(order)
        self.assertEqual(len(events), 2)
        first, second = (json.loads(event.payload) for event in events)
        self.assertEqual(first["delivery"]["lines"][0]["quantity"], 6.0)
        self.assertFalse(first["fully_delivered"])
        self.assertEqual(second["delivery"]["lines"][0]["quantity"], 4.0)
        self.assertTrue(second["fully_delivered"])

    def test_partial_delivery_without_backorder_has_nothing_left_to_deliver(self):
        """6 de 10 sin entrega pendiente: las 4 se cancelan y no llegará otro aviso, así que
        fully_delivered es true (ya no queda nada por entregar). Lo entregado va en las líneas."""
        order = self._order(quantity=10)
        delivery = order.picking_ids
        self._deliver(delivery, 6, cancel_backorder=True)
        self.assertEqual(order.picking_ids, delivery, "Sin entrega pendiente")
        payload = json.loads(self._events(order).payload)
        self.assertEqual(payload["delivery"]["lines"][0]["quantity"], 6.0)
        self.assertTrue(payload["fully_delivered"])

    def test_only_orders_created_by_the_api_notify(self):
        order = self._order(api=False, ref="NO-API")
        self._deliver(order.picking_ids, 10)
        self.assertFalse(self._events(order))

    def test_returns_do_not_notify(self):
        """Solo avisan las entregas al cliente: la devolución de un pedido de la API no."""
        order = self._order()
        delivery = order.picking_ids
        self._deliver(delivery, 10)
        wizard = self.env["stock.return.picking"].create({"picking_id": delivery.id})
        wizard.product_return_moves.quantity = 10
        return_picking = self.env["stock.picking"].browse(wizard.action_create_returns()["res_id"])
        self.assertEqual(return_picking.picking_type_code, "incoming")
        # La devolución queda en el mismo pedido de la API: lo único que la frena es el tipo de operación.
        self.assertEqual(return_picking.sale_id, order)
        self._deliver(return_picking, 10)
        self.assertEqual(return_picking.state, "done")
        self.assertEqual(self._events(order).picking_id, delivery, "Solo el aviso de la entrega")

    def test_without_url_nothing_is_queued(self):
        self.env["ir.config_parameter"].sudo().set_param("shop_integration_api.webhook_url", False)
        order = self._order()
        self._deliver(order.picking_ids, 10)
        self.assertFalse(self._events(order))

    def test_settings_store_url_and_secret(self):
        self.env["res.config.settings"].create(
            {"shop_webhook_url": "https://otra.example.com/avisos", "shop_webhook_secret": "otra-clave"}
        ).execute()
        params = self.env["ir.config_parameter"].sudo()
        self.assertEqual(params.get_param("shop_integration_api.webhook_url"), "https://otra.example.com/avisos")
        self.assertEqual(params.get_param("shop_integration_api.webhook_secret"), "otra-clave")

    def test_only_admins_see_the_notices(self):
        order = self._order()
        self._deliver(order.picking_ids, 10)
        with self.assertRaises(AccessError):
            self.env["shop.webhook.event"].with_user(self.warehouse_user).search([])
        admin = new_test_user(self.env, login="shop_webhook_admin", groups="base.group_system")
        self.assertTrue(self.env["shop.webhook.event"].with_user(admin).search([]))


@tagged("post_install", "-at_install")
class TestApiOrderFlag(HttpCase):
    """Los pedidos creados por POST /api/v1/orders quedan marcados para el aviso."""

    def test_post_marks_the_order(self):
        user = new_test_user(self.env, login="shop_flag_user", groups="base.group_user,sales_team.group_sale_salesman")
        key = self.env["res.users.apikeys"].with_user(user)._generate(
            "rpc", "tienda-prueba", fields.Datetime.now() + timedelta(days=30)
        )
        self.env["res.partner"].with_context(no_vat_validation=True).create(
            {"name": "Cliente marca", "is_company": True, "vat": "J-33333333-3"}
        )
        self.env["product.product"].create({"name": "Mesa marca", "default_code": "MARCA-001"})
        body = {"customer_rif": "J-33333333-3", "external_ref": "WEB-MARCA", "lines": [{"default_code": "MARCA-001", "quantity": 1}]}
        response = self.opener.post(
            self.base_url() + "/api/v1/orders",
            data=json.dumps(body),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            timeout=12,
        )
        self.assertEqual(response.status_code, 201, response.text)
        order = self.env["sale.order"].browse(response.json()["id"])
        self.assertTrue(order.shop_api_order)
