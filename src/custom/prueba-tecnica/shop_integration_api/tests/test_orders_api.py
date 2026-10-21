import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields, models
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.shop_integration_api.controllers.main import ShopIntegrationController

ORDERS_URL = "/api/v1/orders"
PRODUCTS_URL = "/api/v1/products"
RIF = "J-12345678-9"
SECRET_REF = "WEB-SECRETO-777"
JSON_HEADERS = {"Content-Type": "application/json"}


@tagged("post_install", "-at_install")
class TestOrdersApi(HttpCase):
    """Contrato de POST /api/v1/orders, de la autenticación con clave y del log de
    llamadas. El usuario de la tienda es interno con «solo documentos propios»."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.store_user = new_test_user(
            cls.env, login="shop_store_user", groups="base.group_user,sales_team.group_sale_salesman"
        )
        cls.other_salesman = new_test_user(
            cls.env, login="shop_other_salesman", groups="base.group_user,sales_team.group_sale_salesman"
        )
        cls.portal_user = new_test_user(cls.env, login="shop_portal_user_b", groups="base.group_portal")
        # Interno sin ningún grupo de Ventas: no puede crear pedidos.
        cls.no_sales_user = new_test_user(cls.env, login="shop_no_sales_user", groups="base.group_user")
        cls.admin_user = new_test_user(cls.env, login="shop_log_admin", groups="base.group_system")
        cls.store_key = cls._make_key(cls.store_user)

        # Sin validación de RIF/VAT de otros módulos: el formato lo decide esta API.
        Partner = cls.env["res.partner"].with_context(no_vat_validation=True)
        cls.customer = Partner.create(
            {"name": "Cliente Tienda", "is_company": True, "vat": RIF, "user_id": cls.other_salesman.id}
        )
        cls.contact = Partner.create(
            {"name": "Contacto Tienda", "parent_id": cls.customer.id, "vat": "j 12345678.9"}
        )
        # RIF escrito de otra forma en la ficha: se debe encontrar igual.
        cls.customer_plain = Partner.create(
            {"name": "Cliente Sin Guiones", "is_company": True, "vat": "v 98765432-1"}
        )
        cls.dup_1 = Partner.create({"name": "Duplicado 1", "is_company": True, "vat": "G-11111111-1"})
        cls.dup_2 = Partner.create({"name": "Duplicado 2", "is_company": True, "vat": "g111111111"})

        Product = cls.env["product.product"]
        cls.prod_a = Product.create({"name": "Escritorio B", "default_code": "TIENDA-B-001", "list_price": 100.0})
        cls.prod_b = Product.create({"name": "Silla B", "default_code": "TIENDA-B-002", "list_price": 40.0})
        cls.prod_not_sale = Product.create(
            {"name": "Insumo B", "default_code": "TIENDA-B-003", "sale_ok": False}
        )
        cls.prod_archived = Product.create({"name": "Archivado B", "default_code": "TIENDA-B-004"})
        cls.prod_archived.active = False
        Product.create({"name": "Repetido B 1", "default_code": "TIENDA-B-DUP"})
        Product.create({"name": "Repetido B 2", "default_code": "TIENDA-B-DUP"})
        Product.create({"name": "Sin código B"})
        # Unidad con redondeo entero: 0.4 queda en 0.
        category = cls.env["uom.category"].create({"name": "Cajas B"})
        box = cls.env["uom.uom"].create(
            {"name": "Caja B", "category_id": category.id, "uom_type": "reference", "rounding": 1.0}
        )
        cls.prod_box = Product.create(
            {"name": "Caja de tornillos B", "default_code": "TIENDA-B-BOX", "uom_id": box.id, "uom_po_id": box.id}
        )

    @classmethod
    def _make_key(cls, user, days=30):
        return (
            cls.env["res.users.apikeys"]
            .with_user(user)
            ._generate("rpc", "tienda-prueba", fields.Datetime.now() + timedelta(days=days))
        )

    # Utilidades

    def _body(self, **overrides):
        body = {
            "customer_rif": RIF,
            "external_ref": SECRET_REF,
            "lines": [
                {"default_code": "TIENDA-B-001", "quantity": 2},
                {"default_code": "TIENDA-B-002", "quantity": 1.5},
            ],
        }
        body.update(overrides)
        return body

    def _post(self, body=None, key=None, raw=None, auth=True):
        headers = dict(JSON_HEADERS)
        if auth:
            headers["Authorization"] = f"Bearer {key or self.store_key}"
        data = raw if raw is not None else json.dumps(self._body() if body is None else body)
        # Se llama a opener.post y no a url_open: url_open manda un GET si el cuerpo viene vacío.
        return self.opener.post(
            self.base_url() + ORDERS_URL, data=data, headers=headers, allow_redirects=False, timeout=12
        )

    def _last_log(self):
        return self.env["shop.api.log"].sudo().search([], order="id desc", limit=1)

    def _assert_error(self, response, status, code, field):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
        error = response.json()["error"]
        self.assertEqual(error["code"], code, response.text)
        self.assertEqual(error["field"], field, response.text)
        self.assertTrue(error["message"], response.text)
        return error

    def _orders_with_ref(self, ref):
        return self.env["sale.order"].sudo().search([("client_order_ref", "=", ref)])

    # Pedido que funciona

    def test_create_order(self):
        response = self._post()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
        body = response.json()
        self.assertEqual(
            set(body),
            {"id", "name", "state", "external_ref", "customer_id", "amount_untaxed", "amount_total", "currency"},
        )
        order = self.env["sale.order"].sudo().browse(body["id"])
        self.assertTrue(order.exists())
        self.assertEqual(body["name"], order.name)
        self.assertEqual(body["state"], "draft")
        self.assertEqual(order.state, "draft")
        self.assertEqual(body["external_ref"], SECRET_REF)
        self.assertEqual(order.client_order_ref, SECRET_REF)
        self.assertEqual(body["customer_id"], self.customer.id)
        self.assertEqual(order.partner_id, self.customer)
        # El vendedor es el usuario de la tienda, no el vendedor del cliente.
        self.assertEqual(order.user_id, self.store_user)
        self.assertEqual(body["amount_untaxed"], 260.0)
        self.assertEqual(body["amount_untaxed"], order.amount_untaxed)
        self.assertEqual(body["amount_total"], order.amount_total)
        self.assertEqual(body["currency"], order.currency_id.name)
        self.assertEqual(
            [(line.product_id, line.product_uom_qty) for line in order.order_line],
            [(self.prod_a, 2.0), (self.prod_b, 1.5)],
        )

    def test_order_does_not_confirm_nor_reserve(self):
        body = self._post().json()
        order = self.env["sale.order"].sudo().browse(body["id"])
        self.assertEqual(order.state, "draft")

    def test_same_code_twice_creates_two_lines(self):
        lines = [{"default_code": "TIENDA-B-001", "quantity": 1}, {"default_code": "TIENDA-B-001", "quantity": 3}]
        response = self._post(self._body(lines=lines))
        self.assertEqual(response.status_code, 201, response.text)
        order = self.env["sale.order"].sudo().browse(response.json()["id"])
        self.assertEqual(order.order_line.mapped("product_uom_qty"), [1.0, 3.0])

    def test_retry_creates_another_order(self):
        """Supuesto 1: la referencia externa no es única en el tramo B."""
        first = self._post(self._body(external_ref="WEB-REINTENTO")).json()["id"]
        second = self._post(self._body(external_ref="WEB-REINTENTO")).json()["id"]
        self.assertNotEqual(first, second)
        self.assertEqual(len(self._orders_with_ref("WEB-REINTENTO")), 2)

    def test_customer_rif_formats(self):
        for rif in ["J-12345678-9", "j123456789", "J.12345678.9", " j 12345678 9 ", "J-123456789"]:
            with self.subTest(rif=rif):
                response = self._post(self._body(customer_rif=rif))
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(response.json()["customer_id"], self.customer.id)
        # Ficha escrita con espacio y minúscula.
        response = self._post(self._body(customer_rif="V-98765432-1"))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["customer_id"], self.customer_plain.id)

    def test_contacts_resolve_to_company(self):
        """El contacto copia el RIF de la empresa: no cuenta como cliente repetido
        y el pedido va a nombre de la empresa."""
        self.assertEqual(self.contact.commercial_partner_id, self.customer)
        response = self._post()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["customer_id"], self.customer.id)

    # Autenticación y permisos

    def test_requires_key(self):
        self._assert_error(self._post(auth=False), 401, "UNAUTHORIZED", None)

    def test_unauthorized_variants(self):
        deleted_user = new_test_user(self.env, login="shop_deleted_key", groups="base.group_user,sales_team.group_sale_salesman")
        deleted_key = self._make_key(deleted_user)
        self.env["res.users.apikeys"].sudo().search([("user_id", "=", deleted_user.id)]).unlink()
        expired_user = new_test_user(self.env, login="shop_expired_key", groups="base.group_user,sales_team.group_sale_salesman")
        expired_key = self._make_key(expired_user)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_users_apikeys SET expiration_date = %s WHERE user_id = %s",
            (fields.Datetime.now() - timedelta(days=1), expired_user.id),
        )
        archived_user = new_test_user(self.env, login="shop_archived_key", groups="base.group_user,sales_team.group_sale_salesman")
        archived_key = self._make_key(archived_user)
        archived_user.active = False
        self.env.flush_all()
        cases = {
            "otro esquema": {"Authorization": f"Basic {self.store_key}"},
            "esquema sin clave": {"Authorization": "Bearer"},
            "esquema con clave vacía": {"Authorization": "Bearer "},
            "clave inválida": {"Authorization": "Bearer " + "0" * 40},
            "clave con una letra cambiada": {"Authorization": "Bearer " + self.store_key[:-1] + "x"},
            "clave borrada": {"Authorization": f"Bearer {deleted_key}"},
            "clave vencida": {"Authorization": f"Bearer {expired_key}"},
            "usuario archivado": {"Authorization": f"Bearer {archived_key}"},
        }
        for name, headers in cases.items():
            with self.subTest(name):
                response = self.url_open(
                    ORDERS_URL, data=json.dumps(self._body()), headers={**JSON_HEADERS, **headers}, allow_redirects=False
                )
                self._assert_error(response, 401, "UNAUTHORIZED", None)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
                self.assertNotIn(self.store_key, response.text)

    def test_scheme_is_case_insensitive(self):
        response = self.url_open(
            ORDERS_URL,
            data=json.dumps(self._body()),
            headers={**JSON_HEADERS, "Authorization": f"bearer {self.store_key}"},
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_post_ignores_session_cookie(self):
        """Una sesión abierta no sirve para crear pedidos: solo la clave."""
        self.authenticate("shop_store_user", "shop_store_user")
        response = self.url_open(ORDERS_URL, data=json.dumps(self._body()), headers=JSON_HEADERS, allow_redirects=False)
        self._assert_error(response, 401, "UNAUTHORIZED", None)
        self.assertFalse(self._orders_with_ref(SECRET_REF))

    def test_portal_user_forbidden(self):
        # Sin grupo interno, Odoo limita las claves a 1 día.
        key = self._make_key(self.portal_user, days=0.5)
        self._assert_error(self._post(key=key), 403, "FORBIDDEN", None)

    def test_user_without_sales_rights_forbidden(self):
        key = self._make_key(self.no_sales_user)
        self._assert_error(self._post(key=key), 403, "FORBIDDEN", None)
        self.assertFalse(self._orders_with_ref(SECRET_REF))

    def test_store_user_sees_only_own_orders(self):
        response = self._post()
        self.assertEqual(response.status_code, 201, response.text)
        own = self.env["sale.order"].browse(response.json()["id"])
        foreign = self.env["sale.order"].sudo().create({"partner_id": self.customer.id, "user_id": self.other_salesman.id})
        visible = self.env["sale.order"].with_user(self.store_user).search([])
        self.assertIn(own, visible)
        self.assertNotIn(foreign, visible)
        # La regla de Odoo también deja ver los pedidos sin vendedor; ninguno de otro vendedor.
        self.assertFalse(visible.filtered(lambda order: order.user_id and order.user_id != self.store_user))

    # Método y cuerpo

    def test_method_not_allowed(self):
        for method in ["PUT", "DELETE", "PATCH"]:
            with self.subTest(method=method):
                response = self.opener.request(
                    method,
                    self.base_url() + ORDERS_URL,
                    headers={"Authorization": f"Bearer {self.store_key}"},
                    allow_redirects=False,
                    timeout=12,
                )
                self._assert_error(response, 405, "METHOD_NOT_ALLOWED", None)
        response = self.url_open(
            ORDERS_URL, headers={"Authorization": f"Bearer {self.store_key}"}, allow_redirects=False
        )
        self._assert_error(response, 405, "METHOD_NOT_ALLOWED", None)
        self.assertEqual(self._last_log().endpoint, "GET /api/v1/orders")

    def test_invalid_json(self):
        for raw in ["", "no es json", '{"a": ', "[]", '"texto"', "42", "null", b"\xff\xfe\x00"]:
            with self.subTest(raw=raw):
                self._assert_error(self._post(raw=raw), 400, "INVALID_JSON", None)

    def test_lone_surrogate_is_invalid_json_not_500(self):
        """JSON bien escrito con un sustituto suelto (\\ud800): no es texto Unicode y no se puede guardar."""
        for raw in [json.dumps({**self._body(), "external_ref": "\ud800"}), json.dumps({"\udfff": 1})]:
            with self.subTest(raw=raw):
                self._assert_error(self._post(raw=raw), 400, "INVALID_JSON", None)

    def test_required_fields(self):
        cases = [
            ({"customer_rif": None}, "customer_rif"),
            ({"customer_rif": ""}, "customer_rif"),
            ({"customer_rif": "   "}, "customer_rif"),
            ({"external_ref": None}, "external_ref"),
            ({"external_ref": ""}, "external_ref"),
            ({"external_ref": "  "}, "external_ref"),
            ({"lines": None}, "lines"),
            ({"lines": []}, "lines"),
            ({"lines": [{"quantity": 1}]}, "lines[0].default_code"),
            ({"lines": [{"default_code": "", "quantity": 1}]}, "lines[0].default_code"),
            ({"lines": [{"default_code": "TIENDA-B-001", "quantity": 1}, {"default_code": "TIENDA-B-002"}]}, "lines[1].quantity"),
            ({"lines": [{"default_code": "TIENDA-B-001", "quantity": None}]}, "lines[0].quantity"),
        ]
        for overrides, field in cases:
            with self.subTest(overrides=overrides):
                self._assert_error(self._post(self._body(**overrides)), 422, "REQUIRED_FIELD", field)
        for missing in ["customer_rif", "external_ref", "lines"]:
            with self.subTest(missing=missing):
                body = self._body()
                del body[missing]
                self._assert_error(self._post(body), 422, "REQUIRED_FIELD", missing)

    def test_invalid_fields(self):
        ok = {"default_code": "TIENDA-B-001", "quantity": 1}
        cases = [
            ({"customer_rif": 123456789}, "customer_rif"),
            ({"customer_rif": "J-1234567-9"}, "customer_rif"),
            ({"customer_rif": "X-12345678-9"}, "customer_rif"),
            ({"customer_rif": "J-12345678-9-1"}, "customer_rif"),
            ({"customer_rif": "J\t123456789"}, "customer_rif"),
            ({"customer_rif": "J-１２３４５６７８-９"}, "customer_rif"),
            ({"external_ref": 1001}, "external_ref"),
            ({"lines": "TIENDA-B-001"}, "lines"),
            ({"lines": {"default_code": "TIENDA-B-001"}}, "lines"),
            ({"lines": [ok, "TIENDA-B-001"]}, "lines[1]"),
            ({"lines": [{"default_code": 5, "quantity": 1}]}, "lines[0].default_code"),
            ({"lines": [{"default_code": "TIENDA-B-001", "quantity": "2"}]}, "lines[0].quantity"),
            ({"lines": [ok, {"default_code": "TIENDA-B-001", "quantity": True}]}, "lines[1].quantity"),
            ({"lines": [{"default_code": "TIENDA-B-001", "quantity": [1]}]}, "lines[0].quantity"),
            ({"price": 10}, "price"),
            ({"lines": [{"default_code": "TIENDA-B-001", "quantity": 1, "price": 1}]}, "lines[0].price"),
            # Un campo de la versión anterior del contrato también es desconocido.
            ({"lines": [{"code": "TIENDA-B-001", "quantity": 1}]}, "lines[0].code"),
        ]
        for overrides, field in cases:
            with self.subTest(overrides=overrides):
                self._assert_error(self._post(self._body(**overrides)), 422, "INVALID_FIELD", field)

    def test_non_finite_and_huge_quantity(self):
        for literal in ["NaN", "Infinity", "-Infinity", "1e999", "1" + "0" * 400]:
            with self.subTest(literal=literal):
                raw = '{"customer_rif": "%s", "external_ref": "X", "lines": [{"default_code": "TIENDA-B-001", "quantity": %s}]}' % (RIF, literal)
                response = self._post(raw=raw)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["error"]["field"], "lines[0].quantity")

    def test_shape_is_checked_before_lookups(self):
        """El RIF no existe y la línea 0 tampoco, pero la línea 1 tiene mal la forma:
        gana el error de forma."""
        body = self._body(
            customer_rif="J-00000000-0",
            lines=[{"default_code": "NO-EXISTE", "quantity": 1}, {"default_code": "TIENDA-B-001", "quantity": "x"}],
        )
        self._assert_error(self._post(body), 422, "INVALID_FIELD", "lines[1].quantity")

    def test_customer_not_found(self):
        self._assert_error(
            self._post(self._body(customer_rif="J-00000000-0")), 422, "CUSTOMER_NOT_FOUND", "customer_rif"
        )

    def test_customer_is_looked_up_before_products(self):
        body = self._body(customer_rif="J-00000000-0", lines=[{"default_code": "NO-EXISTE", "quantity": 1}])
        self._assert_error(self._post(body), 422, "CUSTOMER_NOT_FOUND", "customer_rif")

    def test_ambiguous_customer(self):
        self._assert_error(
            self._post(self._body(customer_rif="G-11111111-1")), 422, "AMBIGUOUS_REFERENCE", "customer_rif"
        )

    def test_product_not_found(self):
        for code in ["NO-EXISTE", "tienda-b-001", "TIENDA-B-003", "TIENDA-B-004", "TIENDA-B-001 "]:
            with self.subTest(code=code):
                lines = [{"default_code": "TIENDA-B-001", "quantity": 1}, {"default_code": code, "quantity": 1}]
                error = self._assert_error(
                    self._post(self._body(lines=lines)), 422, "PRODUCT_NOT_FOUND", "lines[1].default_code"
                )
                self.assertEqual(error["message"], f"No existe un producto con el código {code}")

    def test_first_failing_line_wins(self):
        lines = [
            {"default_code": "TIENDA-B-001", "quantity": 1},
            {"default_code": "NO-EXISTE-2", "quantity": 1},
            {"default_code": "NO-EXISTE-3", "quantity": 1},
        ]
        self._assert_error(self._post(self._body(lines=lines)), 422, "PRODUCT_NOT_FOUND", "lines[1].default_code")

    def test_ambiguous_product(self):
        lines = [{"default_code": "TIENDA-B-001", "quantity": 1}, {"default_code": "TIENDA-B-DUP", "quantity": 1}]
        self._assert_error(self._post(self._body(lines=lines)), 422, "AMBIGUOUS_REFERENCE", "lines[1].default_code")

    def test_invalid_quantity(self):
        for quantity in [0, 0.0, -1, -0.5]:
            with self.subTest(quantity=quantity):
                lines = [{"default_code": "TIENDA-B-001", "quantity": 1}, {"default_code": "TIENDA-B-002", "quantity": quantity}]
                self._assert_error(self._post(self._body(lines=lines)), 422, "INVALID_QUANTITY", "lines[1].quantity")

    def test_quantity_rounds_to_zero_in_unit_of_measure(self):
        lines = [{"default_code": "TIENDA-B-BOX", "quantity": 0.4}]
        self._assert_error(self._post(self._body(lines=lines)), 422, "INVALID_QUANTITY", "lines[0].quantity")
        ok = self._post(self._body(lines=[{"default_code": "TIENDA-B-BOX", "quantity": 0.6}]))
        self.assertEqual(ok.status_code, 201, ok.text)

    def test_failed_calls_create_nothing(self):
        before = self.env["sale.order"].sudo().search_count([])
        self._post(self._body(lines=[{"default_code": "NO-EXISTE", "quantity": 1}]))
        self._post(self._body(customer_rif="J-00000000-0"))
        self._post(raw="no es json")
        self.assertEqual(self.env["sale.order"].sudo().search_count([]), before)

    def test_one_lookup_for_customer_and_one_for_products(self):
        """Una búsqueda para el cliente y una para todos los productos, no una por línea."""
        lines = [{"default_code": "TIENDA-B-001", "quantity": 1}, {"default_code": "TIENDA-B-002", "quantity": 1}] * 3
        with (
            patch.object(
                ShopIntegrationController, "_find_customer", autospec=True, side_effect=ShopIntegrationController._find_customer
            ) as find_customer,
            patch.object(
                ShopIntegrationController, "_find_products", autospec=True, side_effect=ShopIntegrationController._find_products
            ) as find_products,
        ):
            response = self._post(self._body(lines=lines))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(find_customer.call_count, 1)
        self.assertEqual(find_products.call_count, 1)

    # Fallos a medias

    def test_unexpected_error_rolls_back_and_is_logged(self):
        with (
            patch.object(
                ShopIntegrationController, "_order_response", side_effect=RuntimeError("detalle interno")
            ),
            self.assertLogs("odoo.addons.shop_integration_api", level="ERROR"),
        ):
            response = self._post(self._body(external_ref="WEB-A-MEDIAS"))
        self._assert_error(response, 500, "INTERNAL_ERROR", None)
        self.assertNotIn("detalle interno", response.text)
        # El pedido que ya se había escrito se deshizo, y el log quedó.
        self.assertFalse(self._orders_with_ref("WEB-A-MEDIAS"))
        log = self._last_log()
        self.assertEqual((log.status_code, log.error_code, log.user_id), (500, "INTERNAL_ERROR", self.store_user))

    # Log de llamadas

    def test_log_of_successful_call(self):
        before = self.env["shop.api.log"].sudo().search_count([])
        self.assertEqual(self._post().status_code, 201)
        self.assertEqual(self.env["shop.api.log"].sudo().search_count([]), before + 1)
        log = self._last_log()
        self.assertEqual(log.endpoint, "POST /api/v1/orders")
        self.assertEqual(log.user_id, self.store_user)
        self.assertEqual(log.status_code, 201)
        self.assertFalse(log.error_code)
        self.assertIsInstance(log.duration_ms, int)
        self.assertGreaterEqual(log.duration_ms, 0)
        self.assertTrue(log.create_date)

    def test_log_of_failed_calls(self):
        cases = [
            (self._post(auth=False), 401, "UNAUTHORIZED", False),
            (self._post(raw="no es json"), 400, "INVALID_JSON", self.store_user),
            (self._post(self._body(lines=[])), 422, "REQUIRED_FIELD", self.store_user),
            (self._post(self._body(customer_rif="J-00000000-0")), 422, "CUSTOMER_NOT_FOUND", self.store_user),
        ]
        for response, status, code, user in cases:
            with self.subTest(code=code):
                self.assertEqual(response.status_code, status)
        logs = self.env["shop.api.log"].sudo().search([], order="id desc", limit=len(cases))
        for log, (_response, status, code, user) in zip(reversed(logs), cases):
            with self.subTest(log=code):
                self.assertEqual((log.status_code, log.error_code), (status, code))
                self.assertEqual(log.user_id, user or self.env["res.users"])

    def test_log_has_no_sensitive_data(self):
        """Ni la clave, ni el RIF, ni la referencia externa llegan al log."""
        self.assertEqual(self._post(self._body(external_ref=SECRET_REF)).status_code, 201)
        self.assertEqual(self._post(self._body(customer_rif="J-00000000-0")).status_code, 422)
        self.assertEqual(
            self.url_open(
                f"{PRODUCTS_URL}?category_id={self.env.ref('product.product_category_all').id}&modified_since=2026-01-01",
                headers={"Authorization": f"Bearer {self.store_key}"},
            ).status_code,
            200,
        )
        logs = self.env["shop.api.log"].sudo().search([])
        self.assertTrue(logs)
        forbidden = [self.store_key, self.store_key[:8], RIF, "12345678", SECRET_REF, "category_id", "modified_since", "127.0.0.1"]
        for log in logs:
            dump = json.dumps(log.read()[0], default=str)
            for text in forbidden:
                self.assertNotIn(text, dump)
        # El modelo no tiene dónde guardar cabeceras, cuerpo, consulta ni IP.
        custom = set(logs._fields) - set(models.MAGIC_COLUMNS) - {"display_name"}
        self.assertEqual(custom, {"endpoint", "user_id", "status_code", "duration_ms", "error_code"})

    def test_log_access_rights(self):
        Log = self.env["shop.api.log"]
        self._post()
        self.assertEqual(self._last_log().status_code, 201)
        # Quien llama a la API no lee ni escribe el log.
        for user in (self.store_user, self.portal_user, self.no_sales_user):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    Log.with_user(user).search([])
                self.assertFalse(Log.with_user(user).has_access("create"))
        # El administrador lo lee; nadie lo edita.
        admin_log = Log.with_user(self.admin_user)
        self.assertTrue(admin_log.search([]))
        for operation in ("create", "write", "unlink"):
            with self.subTest(operation=operation):
                self.assertFalse(admin_log.has_access(operation))

    def test_log_view_is_a_list(self):
        view = self.env["ir.ui.view"].search([("model", "=", "shop.api.log"), ("type", "=", "list")])
        self.assertTrue(view)
