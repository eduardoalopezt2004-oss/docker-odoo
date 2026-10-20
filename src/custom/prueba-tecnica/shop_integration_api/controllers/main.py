import json
import logging
import math
import re
import time
from datetime import datetime
from urllib.parse import urlencode

from odoo import Command, http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)

ALLOWED_PARAMS = ("category_id", "in_stock", "modified_since", "page", "page_size")
PAGE_PARAMS = ("page", "page_size")
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500
# Mayor valor de una columna integer de PostgreSQL: un id más grande haría
# fallar la consulta con un error de base de datos.
MAX_ID = 2147483647
ID_RE = re.compile(r"[1-9][0-9]*")
# RIF: una letra y 9 dígitos, ya sin guiones, puntos ni espacios y en mayúscula.
RIF_RE = re.compile(r"[VEJPGC][0-9]{9}")
RIF_SEPARATORS_RE = re.compile(r"[-. ]")
ORDER_FIELDS = ("customer_rif", "external_ref", "lines")
LINE_FIELDS = ("default_code", "quantity")
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}:[0-9]{2}:[0-9]{2}Z?)?")


class ApiError(Exception):
    """Error de la API: se responde con el formato {"error": {"code", "field", "message"}}."""

    def __init__(self, status, code, message, field=None, headers=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.headers = headers or []


class InvalidParameter(ApiError):
    """Parámetro de la consulta inválido: se responde 400 con el campo exacto."""

    def __init__(self, field, message):
        super().__init__(400, "INVALID_PARAMETER", message, field)


class ShopIntegrationController(http.Controller):
    # Las rutas van con auth="none" y verifican la clave ellas mismas: auth="bearer"
    # de Odoo rechaza la clave mala con un 401 en texto plano, sin el JSON acordado y
    # sin dejar la llamada en el log. Aceptan todos los métodos para poder responder
    # 405 en JSON y registrar la llamada. csrf=False es seguro porque la clave viaja en
    # una cabecera que el navegador no agrega solo. readonly=False: con auth="none"
    # Odoo abre por defecto un cursor de solo lectura y aquí se escribe el log.
    @http.route("/api/v1/products", type="http", auth="none", csrf=False, readonly=False)
    def products(self, **_params):
        return self._dispatch("/api/v1/products", "GET", self._products, accept_session=True)

    @http.route("/api/v1/orders", type="http", auth="none", csrf=False, readonly=False)
    def orders(self, **_params):
        # Solo clave: aceptar también la cookie de sesión dejaría que otra página web
        # creara pedidos con la sesión abierta de quien navega.
        return self._dispatch("/api/v1/orders", "POST", self._create_order, accept_session=False)

    def _dispatch(self, path, method, handler, accept_session):
        """Autentica, ejecuta ``handler`` dentro de un savepoint y registra la llamada.

        Cualquier resultado, bueno o malo, deja una fila en el log. Si el handler
        falla se deshace lo que alcanzó a escribir, pero el log se escribe igual.
        """
        started = time.monotonic()
        user_id = False
        error_code = False
        try:
            user_id = self._authenticate(accept_session)
            request.update_env(user=user_id)
            env = request.env
            if not env.user._is_internal():
                raise ApiError(403, "FORBIDDEN", env._("Este usuario no tiene acceso a la API."))
            if request.httprequest.method != method:
                raise ApiError(
                    405,
                    "METHOD_NOT_ALLOWED",
                    env._("Método no permitido. Use %s.", method),
                    headers=[("Allow", method)],
                )
            with env.cr.savepoint():
                response = handler()
        except ApiError as error:
            error_code = error.code
            response = self._error(error.status, error.code, error.message, error.field, error.headers)
        except AccessError:
            error_code = "FORBIDDEN"
            # Usuario interno al que le falta un permiso (por ejemplo, una compañía
            # no autorizada o no poder crear pedidos): es un problema de acceso.
            _logger.warning("Acceso denegado en %s %s para el usuario %s", method, path, user_id, exc_info=True)
            response = self._error(403, "FORBIDDEN", request.env._("Este usuario no tiene acceso a estos datos."))
        except Exception:
            error_code = "INTERNAL_ERROR"
            # Cualquier otro error es nuestro, no de la tienda: queda la traza en el
            # log de Odoo y la respuesta mantiene el formato acordado, sin detalles internos.
            _logger.exception("Error inesperado en %s %s", method, path)
            response = self._error(
                500, "INTERNAL_ERROR", request.env._("Error interno del servidor. Intente de nuevo más tarde.")
            )
        duration_ms = round((time.monotonic() - started) * 1000)
        self._write_log(path, user_id, response.status_code, error_code, duration_ms)
        return response

    def _authenticate(self, accept_session):
        """Devuelve el id del usuario dueño de la clave (o de la sesión, si se acepta).

        :raises ApiError: 401 si no hay credenciales válidas
        """
        header = request.httprequest.headers.get("Authorization")
        if header is None and accept_session and request.session.uid:
            return request.session.uid
        unauthorized = ApiError(
            401,
            "UNAUTHORIZED",
            request.env._("Credenciales ausentes o inválidas. Mande la clave en la cabecera Authorization: Bearer."),
            headers=[("WWW-Authenticate", "Bearer")],
        )
        scheme, _space, key = (header or "").partition(" ")
        key = key.strip()
        if scheme.lower() != "bearer" or not key:
            raise unauthorized
        # Se reusa la verificación de res.users.apikeys: clave cifrada, vencimiento.
        user_id = request.env["res.users.apikeys"]._check_credentials(scope="rpc", key=key)
        # sudo() solo para leer si el dueño de la clave sigue activo: el usuario público
        # no puede leer res.users y la verificación de la clave no mira ese dato.
        if not user_id or not request.env["res.users"].sudo().search([("id", "=", user_id)], limit=1):
            raise unauthorized
        return user_id

    def _write_log(self, path, user_id, status_code, error_code, duration_ms):
        try:
            # sudo() solo para crear esta fila: quien llama a la API no puede leer ni
            # escribir el log. El savepoint evita que un fallo del log rompa la respuesta.
            with request.env.cr.savepoint():
                request.env["shop.api.log"].sudo().create(
                    {
                        "endpoint": f"{request.httprequest.method[:16]} {path}",
                        "user_id": user_id or False,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "error_code": error_code,
                    }
                )
        except Exception:
            _logger.exception("No se pudo escribir el log de %s", path)

    def _products(self):
        env = request.env
        args = request.httprequest.args
        domain = self._products_domain(args)
        page, page_size = self._parse_page(args)
        # Los productos se buscan con los permisos del usuario de la API.
        Product = env["product.product"].with_context(display_default_code=False)
        total = Product.search_count(domain)
        products = Product.search(domain, order="id", offset=(page - 1) * page_size, limit=page_size)
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
        next_url = None
        if page * page_size < total:
            # La página siguiente conserva los filtros de esta.
            params = [(name, value) for name, value in args.items(multi=True) if name not in PAGE_PARAMS]
            params += [("page", page + 1), ("page_size", page_size)]
            next_url = "/api/v1/products?" + urlencode(params)
        return request.make_json_response(
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "count": len(result),
                "next": next_url,
                "products": result,
            }
        )

    def _parse_page(self, args):
        """Página (desde 1) y productos por página (de 1 a MAX_PAGE_SIZE) de la consulta."""
        env = request.env
        page = self._parse_positive_int(args, "page", 1, MAX_ID, env._("page debe ser un número entero desde 1: %s"))
        page_size = self._parse_positive_int(
            args,
            "page_size",
            DEFAULT_PAGE_SIZE,
            MAX_PAGE_SIZE,
            env._("page_size debe ser un número entero de 1 a %(max)s: %%s", max=MAX_PAGE_SIZE),
        )
        return page, page_size

    def _parse_positive_int(self, args, name, default, maximum, message):
        if name not in args:
            return default
        value = args[name]
        if not ID_RE.fullmatch(value) or int(value) > maximum:
            raise InvalidParameter(name, message % value)
        return int(value)

    def _create_order(self):
        env = request.env
        if not env["sale.order"].has_access("create"):
            raise ApiError(403, "FORBIDDEN", env._("Este usuario no tiene permiso para crear pedidos."))
        rif, external_ref, lines = self._parse_order(self._json_body())
        partner = self._find_customer(rif)
        products = self._find_products([code for code, _qty in lines])
        order_lines = []
        for index, (code, quantity) in enumerate(lines):
            product = self._single(
                products.get(code),
                f"lines[{index}].default_code",
                env._("No existe un producto con el código %s", code),
            )
            if float_is_zero(quantity, precision_rounding=product.uom_id.rounding):
                raise ApiError(
                    422,
                    "INVALID_QUANTITY",
                    env._("La cantidad %s queda en 0 en la unidad de venta del producto %s.", quantity, code),
                    f"lines[{index}].quantity",
                )
            order_lines.append(Command.create({"product_id": product.id, "product_uom_qty": quantity}))
        # Precios, impuestos y lista de precios los calcula sale.order. El vendedor es
        # el usuario de la tienda: con «solo documentos propios» Odoo no deja crear un
        # pedido cuyo vendedor sea otro (el por defecto sería el del cliente).
        order = env["sale.order"].create(
            {
                "partner_id": partner.id,
                "user_id": env.uid,
                "client_order_ref": external_ref,
                "order_line": order_lines,
            }
        )
        return self._order_response(order)

    def _order_response(self, order):
        return request.make_json_response(
            {
                "id": order.id,
                "name": order.name,
                "state": order.state,
                "external_ref": order.client_order_ref,
                "customer_id": order.partner_id.id,
                "amount_untaxed": order.amount_untaxed,
                "amount_total": order.amount_total,
                "currency": order.currency_id.name,
            },
            status=201,
        )

    def _json_body(self):
        try:
            body = json.loads(request.httprequest.get_data())
        except (ValueError, RecursionError) as exc:
            raise ApiError(400, "INVALID_JSON", request.env._("El cuerpo no es un JSON válido.")) from exc
        if not isinstance(body, dict):
            raise ApiError(400, "INVALID_JSON", request.env._("El cuerpo debe ser un objeto JSON."))
        return body

    def _parse_order(self, body):
        """Revisa la forma de todo el cuerpo, sin consultar la base.

        :return: (RIF normalizado, referencia externa, [(código, cantidad)])
        :raises ApiError: 422 con el campo exacto, el primero que falle
        """
        self._reject_unknown(body, ORDER_FIELDS, "")
        rif = self._required_text(body, "customer_rif", "customer_rif")
        normalized_rif = RIF_SEPARATORS_RE.sub("", rif).upper()
        if not RIF_RE.fullmatch(normalized_rif):
            raise self._invalid_field(
                "customer_rif",
                request.env._("customer_rif debe ser una letra (V, E, J, P, G o C) y 9 dígitos: %s", rif),
            )
        external_ref = self._required_text(body, "external_ref", "external_ref")
        raw_lines = body.get("lines")
        if raw_lines is None:
            raise self._required_field("lines")
        if not isinstance(raw_lines, list):
            raise self._invalid_field("lines", request.env._("lines debe ser una lista."))
        if not raw_lines:
            raise self._required_field("lines", request.env._("lines debe traer al menos una línea."))
        lines = []
        for index, line in enumerate(raw_lines):
            path = f"lines[{index}]"
            if not isinstance(line, dict):
                raise self._invalid_field(path, request.env._("%s debe ser un objeto.", path))
            self._reject_unknown(line, LINE_FIELDS, f"{path}.")
            code = self._required_text(line, "default_code", f"{path}.default_code")
            lines.append((code, self._quantity(line, f"{path}.quantity")))
        return normalized_rif, external_ref, lines

    def _reject_unknown(self, data, allowed, prefix):
        for name in data:
            if name not in allowed:
                raise self._invalid_field(
                    f"{prefix}{name}",
                    request.env._("Campo desconocido: %s%s. Los admitidos son %s.", prefix, name, ", ".join(allowed)),
                )

    def _required_text(self, data, name, path):
        value = data.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise self._required_field(path)
        if not isinstance(value, str):
            raise self._invalid_field(path, request.env._("%s debe ser un texto.", path))
        return value

    def _quantity(self, line, path):
        value = line.get("quantity")
        if value is None:
            raise self._required_field(path)
        # bool es un int en Python: true no es una cantidad.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self._invalid_field(path, request.env._("%s debe ser un número, no un texto ni un booleano.", path))
        try:
            quantity = float(value)
        except OverflowError:
            quantity = math.inf
        if not math.isfinite(quantity):
            raise self._invalid_field(path, request.env._("%s debe ser un número finito.", path))
        if quantity <= 0:
            raise ApiError(422, "INVALID_QUANTITY", request.env._("%s debe ser mayor que 0.", path), path)
        return quantity

    def _required_field(self, path, message=None):
        return ApiError(
            422, "REQUIRED_FIELD", message or request.env._("El campo %s es obligatorio.", path), path
        )

    def _invalid_field(self, path, message):
        return ApiError(422, "INVALID_FIELD", message, path)

    def _find_customer(self, rif):
        """Empresa cliente con ese RIF ya normalizado.

        Odoo guarda ``vat`` tal como se escribió, así que se compara quitando
        guiones, puntos y espacios y en mayúscula. Los contactos de una empresa
        copian su RIF: se cuentan por su empresa (``commercial_partner_id``).
        """
        env = request.env
        Partner = env["res.partner"]
        Partner.flush_model(["vat", "active"])
        env.cr.execute(
            """
            SELECT id FROM res_partner
             WHERE active AND UPPER(REGEXP_REPLACE(vat, '[-. ]', '', 'g')) = %s
            """,
            [rif],
        )
        # La búsqueda con el ORM aplica las reglas de registro del usuario de la API.
        partners = Partner.search([("id", "in", [row[0] for row in env.cr.fetchall()])])
        companies = partners.commercial_partner_id
        return self._single(
            companies,
            "customer_rif",
            env._("No existe un cliente con el RIF %s", rif),
            not_found="CUSTOMER_NOT_FOUND",
        )

    def _find_products(self, codes):
        """Productos vendibles de todos los códigos, en una sola búsqueda: {código: productos}."""
        found = {}
        products = request.env["product.product"].search(
            [("default_code", "in", list(set(codes))), ("sale_ok", "=", True)]
        )
        for product in products:
            found[product.default_code] = found.get(product.default_code, product.browse()) | product
        return found

    def _single(self, records, field, not_found_message, not_found="PRODUCT_NOT_FOUND"):
        """El único registro, o el error 422 de «no existe» / «hay más de uno»."""
        if not records:
            raise ApiError(422, not_found, not_found_message, field)
        if len(records) > 1:
            raise ApiError(
                422,
                "AMBIGUOUS_REFERENCE",
                request.env._("Hay más de un registro para esta referencia; no se puede elegir uno."),
                field,
            )
        return records

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
                        "Parámetro desconocido: %s. Los admitidos son category_id, in_stock, modified_since, page y page_size.",
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
            # Lo que devuelve la API vive en cuatro lugares: código en la variante;
            # nombre y precio en la plantilla; precio extra en el valor de atributo
            # de la plantilla, y nombre del atributo en el valor de atributo.
            domain += [
                "|",
                "|",
                "|",
                ("write_date", ">=", since),
                ("product_tmpl_id.write_date", ">=", since),
                ("product_template_attribute_value_ids.write_date", ">=", since),
                ("product_template_attribute_value_ids.product_attribute_value_id.write_date", ">=", since),
            ]
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

    def _error(self, status, code, message, field=None, headers=None):
        return request.make_json_response(
            {"error": {"code": code, "field": field, "message": message}}, headers=headers, status=status
        )
