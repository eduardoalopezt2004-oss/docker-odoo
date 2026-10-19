import logging
import re
from datetime import datetime

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

ALLOWED_PARAMS = ("category_id", "in_stock", "modified_since")
# Mayor valor de una columna integer de PostgreSQL: un id más grande haría
# fallar la consulta con un error de base de datos.
MAX_ID = 2147483647
ID_RE = re.compile(r"[1-9][0-9]*")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}Z?)?")


class InvalidParameter(Exception):
    """Parámetro de la consulta inválido: se responde 400 con el campo exacto."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message


class ShopIntegrationController(http.Controller):
    @http.route("/api/v1/products", type="http", auth="user", methods=["GET"])
    def products(self, **_params):
        env = request.env
        try:
            if not env.user._is_internal():
                return self._error(403, "FORBIDDEN", env._("Este usuario no tiene acceso a la API."))
            domain = self._products_domain(request.httprequest.args)
            # Los productos se buscan con los permisos del usuario de la API.
            products = env["product.product"].with_context(display_default_code=False).search(domain, order="id")
            # sudo() solo para calcular free_qty de estos productos: el cálculo lee
            # stock.move, que pide el grupo Inventario / Usuario, y la API solo
            # devuelve el número. Las compañías siguen siendo las del usuario.
            quantities = {row["id"]: row["free_qty"] for row in products.sudo().read(["free_qty"])}
            result = [
                {
                    "id": product.id,
                    "code": product.default_code or None,
                    "name": product.display_name,
                    "price": product.lst_price,
                    "quantity": quantities[product.id],
                }
                for product in products
            ]
        except InvalidParameter as error:
            return self._error(400, "INVALID_PARAMETER", error.message, error.field)
        except Exception:
            # Cualquier otro error es nuestro, no de la tienda: queda la traza en el
            # log y la respuesta mantiene el formato acordado, sin detalles internos.
            _logger.exception("Error inesperado en GET /api/v1/products")
            return self._error(
                500, "INTERNAL_ERROR", env._("Error interno del servidor. Intente de nuevo más tarde.")
            )
        return request.make_json_response({"count": len(result), "products": result})

    def _products_domain(self, args):
        """Dominio de productos activos y vendibles según los filtros de la consulta.

        :param args: parámetros de la URL (MultiDict de werkzeug)
        """
        env = request.env
        for name, values in args.lists():
            if name not in ALLOWED_PARAMS:
                raise InvalidParameter(
                    name,
                    env._(
                        "Parámetro desconocido: %s. Los admitidos son category_id, in_stock y modified_since.",
                        name,
                    ),
                )
            if len(values) > 1:
                raise InvalidParameter(name, env._("El parámetro %s se envió más de una vez.", name))

        # active=True lo aplica el ORM por defecto.
        domain = [("sale_ok", "=", True)]
        if "category_id" in args:
            category = self._parse_category(args["category_id"])
            domain.append(("categ_id", "child_of", category.id))
        if "in_stock" in args:
            if self._parse_bool(args["in_stock"]):
                domain.append(("free_qty", ">", 0))
        if "modified_since" in args:
            since = self._parse_datetime(args["modified_since"])
            # Nombre y precio viven en la plantilla; el código, en la variante.
            domain += ["|", ("write_date", ">=", since), ("product_tmpl_id.write_date", ">=", since)]
        return domain

    def _parse_category(self, value):
        env = request.env
        if not ID_RE.fullmatch(value) or int(value) > MAX_ID:
            raise InvalidParameter(
                "category_id",
                env._("category_id debe ser un número entero positivo (el id de la categoría): %s", value),
            )
        category = env["product.category"].browse(int(value)).exists()
        if not category:
            raise InvalidParameter("category_id", env._("No existe una categoría con id %s.", value))
        return category

    def _parse_bool(self, value):
        if value not in ("true", "false"):
            raise InvalidParameter("in_stock", request.env._("in_stock debe ser true o false: %s", value))
        return value == "true"

    def _parse_datetime(self, value):
        """Fecha AAAA-MM-DD o AAAA-MM-DDTHH:MM:SS, en UTC (Z opcional)."""
        error = InvalidParameter(
            "modified_since",
            request.env._("Fecha no válida: %s. Use AAAA-MM-DD o AAAA-MM-DDTHH:MM:SS, en UTC.", value),
        )
        if not DATE_RE.fullmatch(value):
            raise error
        date_format = "%Y-%m-%dT%H:%M:%S" if "T" in value else "%Y-%m-%d"
        try:
            return datetime.strptime(value.removesuffix("Z"), date_format)
        except ValueError as exc:
            # Formato correcto pero fecha imposible (2026-02-30): mismo error.
            raise error from exc

    def _error(self, status, code, message, field=None):
        return request.make_json_response(
            {"error": {"code": code, "field": field, "message": message}}, status=status
        )
