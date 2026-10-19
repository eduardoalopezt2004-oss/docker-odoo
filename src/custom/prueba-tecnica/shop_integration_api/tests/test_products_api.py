import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.shop_integration_api.controllers.main import ShopIntegrationController

API_URL = "/api/v1/products"
OLD_DATE = "2020-01-01 00:00:00"
RECENT_DATE = "2025-06-01 12:00:00"


@tagged("post_install", "-at_install")
class TestProductsApi(HttpCase):
    """Contrato de GET /api/v1/products, probado con un usuario interno sin
    grupos de Ventas ni de Inventario (el usuario que usaría la tienda)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_user = new_test_user(cls.env, login="shop_api_user", groups="base.group_user")
        cls.portal_user = new_test_user(cls.env, login="shop_portal_user", groups="base.group_portal")

        Category = cls.env["product.category"]
        cls.categ_parent = Category.create({"name": "Tienda API"})
        cls.categ_child = Category.create({"name": "Sillas", "parent_id": cls.categ_parent.id})
        cls.categ_other = Category.create({"name": "Otra categoría API"})

        def product(name, categ, code=False, **vals):
            return cls.env["product.product"].create(
                {"name": name, "default_code": code, "categ_id": categ.id, "is_storable": True, **vals}
            )

        cls.p_stock = product("Escritorio API", cls.categ_parent, "API-001", list_price=150.0)
        cls.p_child = product("Silla API", cls.categ_child, "API-002", list_price=40.0)
        cls.p_no_stock = product("Lámpara API", cls.categ_parent, "API-003")
        cls.p_reserved = product("Mesa API", cls.categ_parent, "API-004")
        cls.p_service = product("Instalación API", cls.categ_parent, type="service", is_storable=False)
        cls.p_other = product("Estante API", cls.categ_other, "API-005")
        cls.p_archived = product("Archivado API", cls.categ_parent, "API-006")
        cls.p_not_sale = product("Insumo interno API", cls.categ_parent, "API-007", sale_ok=False)

        Quant = cls.env["stock.quant"]
        stock = cls.env.ref("stock.stock_location_stock")
        for prod, qty in [
            (cls.p_stock, 8),
            (cls.p_child, 3),
            (cls.p_reserved, 2),
            (cls.p_other, 4),
            (cls.p_archived, 5),
            (cls.p_not_sale, 5),
        ]:
            Quant._update_available_quantity(prod, stock, qty)
        # Todo lo que hay de la Mesa está reservado: a mano 2, libre 0.
        Quant._update_reserved_quantity(cls.p_reserved, stock, 2)
        cls.p_archived.active = False

        # Fechas de modificación fijas. Escritorio: variante y plantilla recientes;
        # Silla: solo la plantilla (donde viven nombre y precio); Lámpara: solo la variante.
        products = cls.p_stock | cls.p_child | cls.p_no_stock | cls.p_reserved | cls.p_service | cls.p_other
        cls.env.flush_all()
        cr = cls.env.cr
        cr.execute("UPDATE product_product SET write_date = %s WHERE id IN %s", (OLD_DATE, tuple(products.ids)))
        cr.execute(
            "UPDATE product_template SET write_date = %s WHERE id IN %s",
            (OLD_DATE, tuple(products.product_tmpl_id.ids)),
        )
        cr.execute(
            "UPDATE product_product SET write_date = %s WHERE id IN %s",
            (RECENT_DATE, (cls.p_stock.id, cls.p_no_stock.id)),
        )
        cr.execute(
            "UPDATE product_template SET write_date = %s WHERE id IN %s",
            (RECENT_DATE, (cls.p_stock.product_tmpl_id.id, cls.p_child.product_tmpl_id.id)),
        )
        cls.env.invalidate_all()
        cls.ours = products | cls.p_archived | cls.p_not_sale

    def _get(self, query="", login="shop_api_user"):
        if login:
            self.authenticate(login, login)
        return self.url_open(f"{API_URL}{query}", allow_redirects=False)

    def _ids(self, query=""):
        """Ids devueltos que pertenecen a los productos de esta prueba
        (la base puede traer productos de demostración)."""
        response = self._get(query)
        self.assertEqual(response.status_code, 200, response.text)
        return {p["id"] for p in response.json()["products"]} & set(self.ours.ids)

    def _assert_invalid(self, query, field):
        response = self._get(query)
        self.assertEqual(response.status_code, 400, f"{query}: {response.text}")
        self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
        error = response.json()["error"]
        self.assertEqual(error["code"], "INVALID_PARAMETER", query)
        self.assertEqual(error["field"], field, query)
        self.assertTrue(error["message"], query)
        return error

    # Sin filtros y formato

    def test_without_filters_only_active_and_saleable(self):
        ids = self._ids()
        expected = self.p_stock | self.p_child | self.p_no_stock | self.p_reserved | self.p_service | self.p_other
        self.assertEqual(ids, set(expected.ids))

    def test_response_format(self):
        response = self._get(f"?category_id={self.categ_parent.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
        body = response.json()
        self.assertEqual(set(body), {"count", "products"})
        self.assertEqual(body["count"], len(body["products"]))
        ids = [p["id"] for p in body["products"]]
        self.assertEqual(ids, sorted(ids), "La lista va ordenada por id")
        by_id = {p["id"]: p for p in body["products"]}
        self.assertEqual(
            by_id[self.p_stock.id],
            {"id": self.p_stock.id, "code": "API-001", "name": "Escritorio API", "price": 150.0, "quantity": 8.0},
        )
        # Servicio sin código: code null y cantidad 0.
        self.assertEqual(by_id[self.p_service.id]["code"], None)
        self.assertEqual(by_id[self.p_service.id]["quantity"], 0.0)
        # La cantidad es la libre (a mano menos reservado).
        self.assertEqual(by_id[self.p_reserved.id]["quantity"], 0.0)

    # Cada filtro solo

    def test_filter_category_includes_subcategories(self):
        expected = self.p_stock | self.p_child | self.p_no_stock | self.p_reserved | self.p_service
        self.assertEqual(self._ids(f"?category_id={self.categ_parent.id}"), set(expected.ids))
        self.assertEqual(self._ids(f"?category_id={self.categ_child.id}"), {self.p_child.id})

    def test_filter_in_stock(self):
        response = self._get("?in_stock=true")
        self.assertEqual(response.status_code, 200, response.text)
        products = response.json()["products"]
        self.assertTrue(all(p["quantity"] > 0 for p in products))
        ids = {p["id"] for p in products} & set(self.ours.ids)
        self.assertEqual(ids, {self.p_stock.id, self.p_child.id, self.p_other.id})
        # Sin stock, todo reservado o servicio: fuera.
        self.assertNotIn(self.p_reserved.id, ids)

    def test_filter_in_stock_false_is_no_filter(self):
        self.assertEqual(self._ids("?in_stock=false"), self._ids())

    def test_filter_modified_since(self):
        recent = {self.p_stock.id, self.p_child.id, self.p_no_stock.id}
        self.assertEqual(self._ids("?modified_since=2025-01-01"), recent)
        # Límite incluido, en UTC, con o sin Z.
        self.assertEqual(self._ids("?modified_since=2025-06-01T12:00:00"), recent)
        self.assertEqual(self._ids("?modified_since=2025-06-01T12:00:00Z"), recent)
        self.assertEqual(self._ids("?modified_since=2025-06-01T12:00:01"), set())
        # Fecha futura: lista vacía, no error.
        response = self._get("?modified_since=2099-01-01")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"count": 0, "products": []})

    def test_filter_modified_since_variant_attributes(self):
        """El precio extra y el nombre del valor de atributo cambian lo que devuelve
        la API sin tocar la variante ni la plantilla: también cuentan."""
        attribute = self.env["product.attribute"].create(
            {"name": "Talla API", "value_ids": [(0, 0, {"name": "S"}), (0, 0, {"name": "XL"})]}
        )
        value_s, value_xl = attribute.value_ids
        template = self.env["product.template"].create(
            {
                "name": "Camisa API",
                "list_price": 20.0,
                "attribute_line_ids": [(0, 0, {"attribute_id": attribute.id, "value_ids": [(6, 0, attribute.value_ids.ids)]})],
            }
        )
        ptav_xl = template.attribute_line_ids.product_template_value_ids.filtered(
            lambda v: v.product_attribute_value_id == value_xl
        )
        ptav_xl.price_extra = 10.0
        variant_s = template.product_variant_ids.filtered(lambda p: p.product_template_attribute_value_ids.name == "S")
        variant_xl = template.product_variant_ids - variant_s

        self.env.flush_all()
        cr = self.env.cr
        ptavs = template.attribute_line_ids.product_template_value_ids
        cr.execute(
            "UPDATE product_product SET write_date = %s WHERE id IN %s",
            (OLD_DATE, tuple(template.product_variant_ids.ids)),
        )
        cr.execute("UPDATE product_template SET write_date = %s WHERE id = %s", (OLD_DATE, template.id))
        cr.execute(
            "UPDATE product_template_attribute_value SET write_date = %s WHERE id IN %s", (OLD_DATE, tuple(ptavs.ids))
        )
        cr.execute(
            "UPDATE product_attribute_value SET write_date = %s WHERE id IN %s",
            (OLD_DATE, tuple(attribute.value_ids.ids)),
        )
        self.env.invalidate_all()

        def changed_variants():
            response = self._get("?modified_since=2025-01-01")
            self.assertEqual(response.status_code, 200, response.text)
            return {p["id"]: p for p in response.json()["products"] if p["id"] in template.product_variant_ids.ids}

        self.assertEqual(changed_variants(), {})
        # Precio extra de XL cambiado: sale XL, con el nombre del valor y el precio extra.
        cr.execute("UPDATE product_template_attribute_value SET write_date = %s WHERE id = %s", (RECENT_DATE, ptav_xl.id))
        changed = changed_variants()
        self.assertEqual(set(changed), {variant_xl.id})
        self.assertEqual(changed[variant_xl.id]["name"], "Camisa API (XL)")
        self.assertEqual(changed[variant_xl.id]["price"], 30.0)
        # Valor S renombrado: sale también S.
        cr.execute("UPDATE product_attribute_value SET write_date = %s WHERE id = %s", (RECENT_DATE, value_s.id))
        self.assertEqual(set(changed_variants()), {variant_s.id, variant_xl.id})

    # Filtros combinados

    def test_filters_combined(self):
        parent = self.categ_parent.id
        cases = [
            (f"?category_id={parent}&in_stock=true", {self.p_stock.id, self.p_child.id}),
            (f"?category_id={parent}&modified_since=2025-01-01", {self.p_stock.id, self.p_child.id, self.p_no_stock.id}),
            ("?in_stock=true&modified_since=2025-01-01", {self.p_stock.id, self.p_child.id}),
            (f"?category_id={parent}&in_stock=true&modified_since=2025-01-01", {self.p_stock.id, self.p_child.id}),
            (f"?category_id={self.categ_child.id}&in_stock=true&modified_since=2025-01-01", {self.p_child.id}),
            (f"?category_id={self.categ_other.id}&modified_since=2025-01-01", set()),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(self._ids(query), expected)

    # Valores inválidos: 400 claro, nunca 500

    def test_invalid_date(self):
        for value in [
            "2026-13-01",
            "2026-02-30",
            "01/10/2026",
            "2026-1-5",
            "hoy",
            "",
            "2026-10-01T25:00:00",
            "2026-10-01 10:00:00",
            "2026-10-01Z",
            "2026-10-01T10:00:00-04:00",
            "２０２６-10-01",
        ]:
            with self.subTest(value=value):
                error = self._assert_invalid(f"?modified_since={value}", "modified_since")
                self.assertIn("AAAA-MM-DD", error["message"])

    def test_invalid_category(self):
        missing = self.env["product.category"].search([], order="id desc", limit=1).id + 1000
        for value in ["abc", "0", "-1", "1.5", "", "99999999999", str(missing)]:
            with self.subTest(value=value):
                self._assert_invalid(f"?category_id={value}", "category_id")

    def test_invalid_in_stock(self):
        for value in ["yes", "1", "True", ""]:
            with self.subTest(value=value):
                self._assert_invalid(f"?in_stock={value}", "in_stock")

    def test_unknown_and_repeated_parameters(self):
        self._assert_invalid("?categ=1", "categ")
        self._assert_invalid(
            f"?category_id={self.categ_parent.id}&category_id={self.categ_child.id}", "category_id"
        )

    # Acceso y método

    def test_requires_credentials(self):
        response = self._get(login=None)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
        error = response.json()["error"]
        self.assertEqual((error["code"], error["field"]), ("UNAUTHORIZED", None))
        self.assertTrue(error["message"])

    def _get_with_key(self, key, query=""):
        return self.url_open(
            f"{API_URL}{query}", headers={"Authorization": f"Bearer {key}"}, allow_redirects=False
        )

    def test_key_works_like_session(self):
        key = (
            self.env["res.users.apikeys"]
            .with_user(self.api_user)
            ._generate("rpc", "tienda-prueba", fields.Datetime.now() + timedelta(days=30))
        )
        query = f"?category_id={self.categ_parent.id}&in_stock=true"
        by_key = self._get_with_key(key, query)
        self.assertEqual(by_key.status_code, 200, by_key.text)
        by_session = self._get(query)
        self.assertEqual(by_key.json(), by_session.json())
        # Los errores de parámetros son los mismos con clave.
        invalid = self._get_with_key(key, "?categ=1")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()["error"]["code"], "INVALID_PARAMETER")

    def test_invalid_key_is_unauthorized_even_with_session(self):
        """Si viene la cabecera Authorization, manda ella: no se cae a la sesión."""
        self.authenticate("shop_api_user", "shop_api_user")
        response = self._get_with_key("0" * 40)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "UNAUTHORIZED")

    def test_portal_key_forbidden(self):
        key = (
            self.env["res.users.apikeys"]
            .with_user(self.portal_user)
            # Sin grupo interno, Odoo limita las claves a 1 día.
            ._generate("rpc", "tienda-prueba", fields.Datetime.now() + timedelta(hours=12))
        )
        response = self._get_with_key(key)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["error"]["code"], "FORBIDDEN")

    def test_every_get_call_is_logged(self):
        Log = self.env["shop.api.log"].sudo()
        before = Log.search_count([])
        # Primero la llamada sin credenciales: después de autenticar, la cookie de sesión sigue en el cliente.
        self.assertEqual(self._get(login=None).status_code, 401)
        self.assertEqual(self._get().status_code, 200)
        self.assertEqual(self._get("?categ=1").status_code, 400)
        logs = Log.search([], order="id desc", limit=3)
        self.assertEqual(Log.search_count([]), before + 3)
        self.assertEqual(
            [(log.endpoint, log.status_code, log.error_code) for log in reversed(logs)],
            [
                ("GET /api/v1/products", 401, "UNAUTHORIZED"),
                ("GET /api/v1/products", 200, False),
                ("GET /api/v1/products", 400, "INVALID_PARAMETER"),
            ],
        )
        self.assertFalse(logs[-1].user_id)
        self.assertEqual(logs[0].user_id, self.api_user)
        self.assertNotIn("categ", json.dumps(logs.read(), default=str))

    def test_portal_user_forbidden(self):
        response = self._get(login="shop_portal_user")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["error"]["code"], "FORBIDDEN")

    def test_only_get(self):
        self.authenticate("shop_api_user", "shop_api_user")
        response = self.url_open(API_URL, data={"in_stock": "true"}, allow_redirects=False)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
        error = response.json()["error"]
        self.assertEqual((error["code"], error["field"]), ("METHOD_NOT_ALLOWED", None))
        self.assertEqual(response.headers["Allow"], "GET")

    def test_unexpected_error_is_json_without_details(self):
        with (
            patch.object(
                ShopIntegrationController, "_products_domain", side_effect=RuntimeError("detalle interno")
            ),
            self.assertLogs("odoo.addons.shop_integration_api", level="ERROR"),
        ):
            response = self._get()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("detalle interno", response.text)

    def test_access_error_is_forbidden(self):
        with (
            patch.object(
                ShopIntegrationController, "_products_domain", side_effect=AccessError("detalle interno")
            ),
            self.assertLogs("odoo.addons.shop_integration_api", level="WARNING"),
        ):
            response = self._get()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["error"]["code"], "FORBIDDEN")
        self.assertNotIn("detalle interno", response.text)

    def test_api_user_has_no_inventory_rights(self):
        """El sudo() del controlador solo cubre el cálculo de free_qty: el usuario
        de la API sigue sin poder leer ni mover inventario por su cuenta."""
        with self.assertRaises(AccessError):
            self.env["stock.move"].with_user(self.api_user).search([])
        with self.assertRaises(AccessError):
            self.env["stock.quant"].with_user(self.api_user).create(
                {
                    "product_id": self.p_stock.id,
                    "location_id": self.env.ref("stock.stock_location_stock").id,
                    "quantity": 1,
                }
            )
