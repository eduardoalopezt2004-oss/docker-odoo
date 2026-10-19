import logging
import re
import time
from datetime import datetime

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

_logger = logging.getLogger(__name__)

ALLOWED_PARAMS = ("category_id", "in_stock", "modified_since")
# Mayor valor de una columna integer de PostgreSQL: un id más grande haría
# fallar la consulta con un error de base de datos.
MAX_ID = 2147483647
ID_RE = re.compile(r"[1-9][0-9]*")
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
