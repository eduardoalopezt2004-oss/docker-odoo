import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from datetime import timedelta

import requests

from odoo import api, fields, models
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

URL_PARAM = "shop_integration_api.webhook_url"
SECRET_PARAM = "shop_integration_api.webhook_secret"
# Minutos hasta el siguiente intento tras cada fallo: 1, 5, 15 y 60 minutos y luego cada 6 horas
# (unas 25 horas en total). Tras el último fallo el aviso queda «Fallido».
RETRY_MINUTES = [1, 5, 15, 60, 360, 360, 360, 360]
REQUEST_TIMEOUT = 10
BATCH_SIZE = 50
# Tiempo máximo de una corrida del cron; lo que quede vencido sale en la siguiente.
TIME_BUDGET_SECONDS = 60


class ShopWebhookEvent(models.Model):
    """Aviso pendiente o enviado a la tienda en línea.

    La validación de la entrega solo crea la fila; el envío lo hace el cron en segundo plano.
    Así, si la tienda está caída, quien valida no espera ni ve ningún error.
    """

    _name = "shop.webhook.event"
    _description = "Aviso a la tienda en línea"
    _order = "id desc"
    _rec_name = "event_uuid"

    event_uuid = fields.Char(string="Id del aviso", required=True, readonly=True, copy=False, index=True)
    event_type = fields.Selection(
        [("order.delivered", "Pedido entregado")], string="Tipo", required=True, readonly=True
    )
    order_id = fields.Many2one("sale.order", string="Pedido", readonly=True, ondelete="cascade", index=True)
    picking_id = fields.Many2one("stock.picking", string="Entrega", readonly=True, ondelete="cascade")
    payload = fields.Text(string="Contenido (JSON)", required=True, readonly=True)
    state = fields.Selection(
        [("pending", "Pendiente"), ("sent", "Enviado"), ("failed", "Fallido")],
        string="Estado",
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    attempts = fields.Integer(string="Intentos", readonly=True)
    next_attempt = fields.Datetime(string="Próximo intento", default=fields.Datetime.now, readonly=True, index=True)
    last_attempt = fields.Datetime(string="Último intento", readonly=True)
    last_status = fields.Integer(string="Último código HTTP", readonly=True, help="0 si la tienda no respondió.")
    last_error = fields.Char(string="Último error", readonly=True)

    _sql_constraints = [
        ("event_uuid_uniq", "unique(event_uuid)", "El id del aviso ya existe."),
    ]

    @api.model
    def _webhook_settings(self):
        # sudo() solo para leer la URL y el secreto: los parámetros del sistema solo los leen
        # administradores y esto corre también como el almacenista que valida la entrega.
        params = self.env["ir.config_parameter"].sudo()
        return params.get_param(URL_PARAM), params.get_param(SECRET_PARAM)

    @api.model
    def _queue_deliveries(self, pickings):
        """Crea un aviso por cada entrega validada de un pedido creado por la API.

        Corre dentro de la validación: solo escribe filas, nunca habla con la tienda. Sin URL o sin
        secreto configurados no se encola nada (no se envían avisos sin firma).
        """
        url, secret = self._webhook_settings()
        if not (url and secret):
            return self.browse()
        # sudo() solo para estas entregas y sus avisos: quien valida puede ser un almacenista que no
        # lee pedidos de venta ni puede crear avisos (son solo de administradores).
        deliveries = pickings.sudo().filtered(
            lambda picking: picking.state == "done"
            and picking.picking_type_code == "outgoing"
            and picking.sale_id.shop_api_order
        )
        if not deliveries:
            return self.browse()
        events = self.sudo().create([self._prepare_delivery_event(picking) for picking in deliveries])
        self._trigger_cron()
        return events

    @api.model
    def _prepare_delivery_event(self, picking):
        order = picking.sale_id
        event_uuid = str(uuid.uuid4())
        # Sin precios ni datos del cliente: la tienda ya los tiene y el aviso viaja fuera de Odoo.
        payload = {
            "event": "order.delivered",
            "event_id": event_uuid,
            "order": {"id": order.id, "name": order.name, "external_ref": order.client_order_ref or None},
            "delivery": {
                "name": picking.name,
                "date_done": picking.date_done.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lines": [
                    {
                        "product_id": move.product_id.id,
                        "default_code": move.product_id.default_code or None,
                        "quantity": move.quantity,
                    }
                    for move in picking.move_ids
                    if move.state == "done" and move.quantity
                ],
            },
            "fully_delivered": order._shop_fully_delivered(),
        }
        return {
            "event_uuid": event_uuid,
            "event_type": "order.delivered",
            "order_id": order.id,
            "picking_id": picking.id,
            "payload": json.dumps(payload, ensure_ascii=False),
        }

    @api.model
    def _trigger_cron(self, at=None):
        cron = self.env.ref("shop_integration_api.ir_cron_send_shop_webhooks", raise_if_not_found=False)
        if cron:
            # sudo() solo para programar la corrida: quien valida la entrega no tiene permisos sobre ir.cron.
            cron.sudo()._trigger(at)

    @api.model
    def _cron_send_pending(self, limit=BATCH_SIZE):
        """Envía los avisos pendientes cuya hora ya llegó. Lo llama el cron, nunca la validación."""
        url, secret = self._webhook_settings()
        if not (url and secret):
            # Sin configuración no se envía nada; los pendientes esperan a que se configure.
            return
        # Fuera de las pruebas se confirma cada aviso enviado: si el cron se corta a mitad, lo ya
        # enviado no se vuelve a enviar.
        auto_commit = not getattr(threading.current_thread(), "testing", False)
        deadline = time.monotonic() + TIME_BUDGET_SECONDS
        events = self.search(
            [("state", "=", "pending"), ("next_attempt", "<=", fields.Datetime.now())],
            order="next_attempt, id",
            limit=limit,
        )
        for event in events:
            if time.monotonic() > deadline:
                break
            if not event._lock_if_due():
                continue
            event._send(url, secret)
            if auto_commit:
                self.env.cr.commit()  # pylint: disable=invalid-commit
        self._schedule_next_run()

    def _lock_if_due(self):
        """Bloquea la fila si sigue pendiente y vencida. False si otro proceso la tiene o ya cambió."""
        self.ensure_one()
        self.flush_recordset(["state", "next_attempt"])
        self.env.cr.execute(
            SQL(
                "SELECT id FROM %s WHERE id = %s AND state = 'pending' AND next_attempt <= %s FOR UPDATE SKIP LOCKED",
                SQL.identifier(self._table),
                self.id,
                fields.Datetime.now(),
            )
        )
        if not self.env.cr.fetchone():
            return False
        self.invalidate_recordset()
        return True

    def _send(self, url, secret):
        """Un intento de envío; anota el resultado y programa el siguiente si hace falta."""
        self.ensure_one()
        body = self.payload.encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Shop-Event-Id": self.event_uuid,
            "X-Shop-Signature": f"sha256={signature}",
        }
        status, error = 0, False
        try:
            # stream=True: no se descarga el cuerpo de la respuesta, que Odoo no usa; así uno grande
            # o lento no retiene la tarea programada.
            response = requests.post(
                url, data=body, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=False, stream=True
            )
        except requests.RequestException as exc:
            error = self.env._("La tienda no respondió: %s", exc)
        else:
            status = response.status_code
            response.close()
            if not 200 <= status < 300:
                error = self.env._("La tienda respondió con el código HTTP %s.", status)
        now = fields.Datetime.now()
        attempts = self.attempts + 1
        vals = {"attempts": attempts, "last_attempt": now, "last_status": status, "last_error": error}
        if not error:
            vals["state"] = "sent"
        elif attempts > len(RETRY_MINUTES):
            vals["state"] = "failed"
        else:
            vals["next_attempt"] = now + timedelta(minutes=RETRY_MINUTES[attempts - 1])
        if error:
            _logger.warning("Aviso %s a la tienda, intento %s: %s", self.event_uuid, attempts, error)
        self.write(vals)

    def _schedule_next_run(self):
        """Programa el cron para el próximo aviso pendiente, sin esperar a su intervalo de 5 minutos."""
        upcoming = self.search([("state", "=", "pending")], order="next_attempt", limit=1)
        if upcoming:
            self._trigger_cron(max(upcoming.next_attempt, fields.Datetime.now()))

    def action_retry(self):
        """Botón «Reintentar» de un aviso fallido: vuelve a empezar la serie de reintentos."""
        failed = self.filtered(lambda event: event.state == "failed")
        if failed:
            failed.write({"state": "pending", "attempts": 0, "next_attempt": fields.Datetime.now()})
            self._trigger_cron()
        return True
