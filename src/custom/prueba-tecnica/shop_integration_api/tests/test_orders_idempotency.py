import json
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, new_test_user, tagged

ORDERS_URL = "/api/v1/orders"
RIF = "J-22222222-2"


@tagged("post_install", "-at_install")
class TestOrdersIdempotency(HttpCase):
    """Tramo C: con la misma Idempotency-Key, un reintento no crea un segundo pedido."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = "base.group_user,sales_team.group_sale_salesman"
        cls.store_user = new_test_user(cls.env, login="shop_idem_user", groups=groups)
        cls.other_store_user = new_test_user(cls.env, login="shop_idem_other", groups=groups)
        cls.admin_user = new_test_user(cls.env, login="shop_idem_admin", groups="base.group_system")
        cls.key = cls._make_key(cls.store_user)
        cls.other_key = cls._make_key(cls.other_store_user)
        cls.env["res.partner"].with_context(no_vat_validation=True).create(
            {"name": "Cliente Idempotencia", "is_company": True, "vat": RIF}
        )
        cls.env["product.product"].create({"name": "Escritorio C", "default_code": "TIENDA-C-001", "list_price": 100.0})

    @classmethod
    def _make_key(cls, user):
        return (
            cls.env["res.users.apikeys"]
            .with_user(user)
            ._generate("rpc", "tienda-prueba", fields.Datetime.now() + timedelta(days=30))
        )

    def _body(self, ref="WEB-IDEM-1", quantity=2, code="TIENDA-C-001"):
        return {"customer_rif": RIF, "external_ref": ref, "lines": [{"default_code": code, "quantity": quantity}]}

    def _post(self, body, idempotency_key=None, api_key=None, raw=None):
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key or self.key}"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return self.opener.post(
            self.base_url() + ORDERS_URL,
            data=raw if raw is not None else json.dumps(body),
            headers=headers,
            allow_redirects=False,
            timeout=12,
        )

    def _orders(self, ref):
        return self.env["sale.order"].sudo().search([("client_order_ref", "=", ref)])

    def _assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        error = response.json()["error"]
        self.assertEqual(error["code"], code, response.text)
        self.assertEqual(error["field"], "Idempotency-Key", response.text)
        self.assertTrue(error["message"])

    def test_same_key_same_content_returns_the_same_order(self):
        first = self._post(self._body(), "pedido-WEB-IDEM-1")
        self.assertEqual(first.status_code, 201, first.text)
        self.assertNotIn("Idempotent-Replayed", first.headers)
        second = self._post(self._body(), "pedido-WEB-IDEM-1")
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.headers.get("Idempotent-Replayed"), "true")
        self.assertEqual(second.json(), first.json())
        self.assertEqual(len(self._orders("WEB-IDEM-1")), 1)

    def test_same_content_written_differently_is_the_same(self):
        """Mismo JSON con otro orden de campos y otros espacios: es el mismo contenido."""
        first = self._post(self._body(), "pedido-orden")
        raw = '{ "lines": [{"quantity": 2, "default_code": "TIENDA-C-001"}],\n "external_ref": "WEB-IDEM-1", "customer_rif": "%s" }' % RIF
        second = self._post(None, "pedido-orden", raw=raw)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["id"], first.json()["id"])

    def test_same_key_other_content_is_409(self):
        self.assertEqual(self._post(self._body(), "pedido-409").status_code, 201)
        self._assert_error(self._post(self._body(quantity=3), "pedido-409"), 409, "IDEMPOTENCY_KEY_REUSED")
        self._assert_error(self._post(self._body(ref="WEB-OTRO"), "pedido-409"), 409, "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(len(self._orders("WEB-IDEM-1")), 1)
        self.assertFalse(self._orders("WEB-OTRO"))

    def test_without_key_each_post_creates_an_order(self):
        """La cabecera es opcional: sin ella, el POST funciona como en el tramo B."""
        self.assertEqual(self._post(self._body(ref="WEB-SIN-CLAVE")).status_code, 201)
        self.assertEqual(self._post(self._body(ref="WEB-SIN-CLAVE")).status_code, 201)
        self.assertEqual(len(self._orders("WEB-SIN-CLAVE")), 2)

    def test_different_keys_create_different_orders(self):
        self.assertEqual(self._post(self._body(ref="WEB-DOS"), "clave-1").status_code, 201)
        self.assertEqual(self._post(self._body(ref="WEB-DOS"), "clave-2").status_code, 201)
        self.assertEqual(len(self._orders("WEB-DOS")), 2)

    def test_keys_are_per_api_user(self):
        self.assertEqual(self._post(self._body(ref="WEB-USUARIOS"), "compartida").status_code, 201)
        other = self._post(self._body(ref="WEB-USUARIOS", quantity=5), "compartida", api_key=self.other_key)
        self.assertEqual(other.status_code, 201, other.text)
        self.assertEqual(len(self._orders("WEB-USUARIOS")), 2)

    def test_failed_request_does_not_use_the_key(self):
        """Un 422 no guarda la clave: la tienda corrige el cuerpo y reintenta con la misma."""
        failed = self._post(self._body(ref="WEB-CORRIGE", code="NO-EXISTE"), "pedido-corrige")
        self.assertEqual(failed.status_code, 422, failed.text)
        fixed = self._post(self._body(ref="WEB-CORRIGE"), "pedido-corrige")
        self.assertEqual(fixed.status_code, 201, fixed.text)
        replay = self._post(self._body(ref="WEB-CORRIGE"), "pedido-corrige")
        self.assertEqual(replay.json()["id"], fixed.json()["id"])
        self.assertEqual(len(self._orders("WEB-CORRIGE")), 1)

    def test_key_in_use_by_a_request_not_finished_is_409(self):
        """Si otra petición con la misma clave todavía no terminó, se pide reintentar."""
        self.env["shop.idempotency.key"].sudo().create(
            {"user_id": self.store_user.id, "key": "en-curso", "request_hash": "x" * 64}
        )
        self._assert_error(self._post(self._body(ref="WEB-EN-CURSO"), "en-curso"), 409, "IDEMPOTENCY_KEY_IN_USE")
        self.assertFalse(self._orders("WEB-EN-CURSO"))

    def test_invalid_key(self):
        for value in ("", "   ", "x" * 256, "clave\twith-tab", "clave-ñ"):
            with self.subTest(value=value):
                self._assert_error(self._post(self._body(ref="WEB-INVALIDA"), value), 400, "INVALID_IDEMPOTENCY_KEY")
        self.assertFalse(self._orders("WEB-INVALIDA"))

    def test_keys_store_no_body_and_only_admins_read_them(self):
        self.assertEqual(self._post(self._body(ref="WEB-GUARDA"), "pedido-guarda").status_code, 201)
        record = self.env["shop.idempotency.key"].sudo().search([("key", "=", "pedido-guarda")])
        self.assertEqual(record.user_id, self.store_user)
        self.assertEqual(record.order_id, self._orders("WEB-GUARDA"))
        self.assertEqual(len(record.request_hash), 64)
        dump = json.dumps(record.read()[0], default=str)
        self.assertNotIn(RIF, dump)
        # Solo la clave y el resumen (hash) del cuerpo: ni el RIF ni la referencia del pedido.
        self.assertNotIn("WEB-GUARDA", dump)
        with self.assertRaises(AccessError):
            self.env["shop.idempotency.key"].with_user(self.store_user).search([])
        self.assertTrue(self.env["shop.idempotency.key"].with_user(self.admin_user).search([]))
        self.assertFalse(self.env["shop.idempotency.key"].with_user(self.admin_user).has_access("write"))

    def test_unique_key_per_user_in_the_database(self):
        constraints = {name: sql for name, sql, _message in self.env["shop.idempotency.key"]._sql_constraints}
        self.assertEqual(constraints.get("user_key_uniq"), "unique(user_id, key)")
