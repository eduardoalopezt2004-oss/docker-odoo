from odoo.tests import HttpCase, new_test_user, tagged

API_URL = "/api/v1/products"


@tagged("post_install", "-at_install")
class TestProductsPagination(HttpCase):
    """Tramo C: paginación del GET con metadatos y consultas que no crecen con los productos."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        new_test_user(cls.env, login="shop_page_user", groups="base.group_user")
        Category = cls.env["product.category"]
        cls.categ_seven = Category.create({"name": "Paginación siete"})
        cls.seven = cls.env["product.product"].create(
            [{"name": f"Producto página {n}", "default_code": f"PAG-{n:02d}", "categ_id": cls.categ_seven.id} for n in range(7)]
        )
        # Dos categorías con la misma forma y distinta cantidad de productos, con stock.
        cls.categ_small = Category.create({"name": "Consultas pocos"})
        cls.categ_large = Category.create({"name": "Consultas muchos"})
        stock = cls.env.ref("stock.stock_location_stock")
        Quant = cls.env["stock.quant"]
        for categ, size in ((cls.categ_small, 3), (cls.categ_large, 30)):
            products = cls.env["product.product"].create(
                [
                    {"name": f"{categ.name} {n}", "default_code": f"{categ.id}-{n}", "categ_id": categ.id, "is_storable": True}
                    for n in range(size)
                ]
            )
            for product in products:
                Quant._update_available_quantity(product, stock, 5)

    def _get(self, query):
        self.authenticate("shop_page_user", "shop_page_user")
        response = self.url_open(f"{API_URL}{query}", allow_redirects=False)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_pages_with_metadata_and_next(self):
        categ = self.categ_seven.id
        first = self._get(f"?category_id={categ}&page_size=3")
        self.assertEqual(first["total"], 7)
        self.assertEqual(first["page"], 1)
        self.assertEqual(first["page_size"], 3)
        self.assertEqual(first["count"], 3)
        self.assertEqual(first["next"], f"{API_URL}?category_id={categ}&page=2&page_size=3")
        second = self._get(first["next"][len(API_URL):])
        self.assertEqual((second["page"], second["count"]), (2, 3))
        self.assertEqual(second["next"], f"{API_URL}?category_id={categ}&page=3&page_size=3")
        third = self._get(second["next"][len(API_URL):])
        self.assertEqual((third["page"], third["count"], third["next"]), (3, 1, None))
        ids = [p["id"] for page in (first, second, third) for p in page["products"]]
        self.assertEqual(ids, self.seven.ids, "Todas, sin repetir, en orden de id")

    def test_next_keeps_every_filter(self):
        body = self._get(f"?category_id={self.categ_large.id}&in_stock=true&modified_since=2000-01-01&page_size=10")
        self.assertEqual(body["total"], 30)
        self.assertEqual(
            body["next"],
            f"{API_URL}?category_id={self.categ_large.id}&in_stock=true&modified_since=2000-01-01&page=2&page_size=10",
        )

    def test_defaults_and_maximum(self):
        body = self._get(f"?category_id={self.categ_large.id}")
        self.assertEqual((body["page"], body["page_size"], body["count"], body["next"]), (1, 100, 30, None))
        self.assertEqual(self._get(f"?category_id={self.categ_large.id}&page_size=500")["page_size"], 500)

    def test_page_beyond_the_last_is_empty(self):
        body = self._get(f"?category_id={self.categ_seven.id}&page=9&page_size=3")
        self.assertEqual(body, {"total": 7, "page": 9, "page_size": 3, "count": 0, "next": None, "products": []})

    def test_invalid_page_and_page_size(self):
        self.authenticate("shop_page_user", "shop_page_user")
        cases = [("page", value) for value in ("0", "-1", "abc", "1.5", "", "99999999999")]
        cases += [("page_size", value) for value in ("0", "501", "abc", "")]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                response = self.url_open(f"{API_URL}?{name}={value}", allow_redirects=False)
                self.assertEqual(response.status_code, 400, response.text)
                error = response.json()["error"]
                self.assertEqual((error["code"], error["field"]), ("INVALID_PARAMETER", name))

    def test_query_count_does_not_grow_with_products(self):
        """El stock se calcula para toda la página de una vez: 3 o 30 productos, mismas consultas."""
        small = f"?category_id={self.categ_small.id}"
        large = f"?category_id={self.categ_large.id}"
        self._get(large)  # Calienta las cachés de Odoo: la primera llamada siempre consulta más.

        def count_queries(query):
            before = self.cr.sql_log_count
            body = self._get(query)
            return self.cr.sql_log_count - before, body

        small_count, small_body = count_queries(small)
        large_count, large_body = count_queries(large)
        self.assertEqual((small_body["count"], large_body["count"]), (3, 30))
        self.assertTrue(all(p["quantity"] == 5.0 for p in large_body["products"]))
        self.assertEqual(large_count, small_count, f"3 productos: {small_count} consultas; 30: {large_count}")
