import json
import logging
from functools import wraps

from odoo import _
from odoo.exceptions import AccessDenied, MissingError, ValidationError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class HavanoApiControllerMixin:
    """
    Mixin for Havano API controllers using Odoo's native session authentication.
    
    NO MORE TOKENS! Just standard Odoo user/password login.
    Session is maintained via cookies automatically.
    """
    source = "havano_pos"

    # =========================================================================
    # RESPONSE HELPERS
    # =========================================================================

    def _json_response(self, payload, status=200):
        """Standard JSON response wrapper."""
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json; charset=utf-8",
        )

    def _success(self, data=None, message="", status=200):
        """Standard success response."""
        company_ctx = self._get_company_context()
        return {
            "success": True,
            "data": data or {},
            "message": message,
            "company": company_ctx["company"],
            "allowed_companies": company_ctx["allowed_companies"],
        }

    def _error(self, error, code=400, status=None):
        """Standard error response."""
        company_ctx = self._get_company_context()
        return {
            "success": False,
            "error": str(error),
            "code": code,
            "company": company_ctx["company"],
            "allowed_companies": company_ctx["allowed_companies"],
        }

    def _get_company_context(self):
        """Return current company context for multi-company aware clients."""
        company = None
        allowed_companies = []
        try:
            env = request.env
            current = env.company
            if current:
                company = {"id": current.id, "name": current.name}

            if request.session.uid:
                user = env.user.sudo()
                allowed_companies = [
                    {"id": comp.id, "name": comp.name}
                    for comp in user.company_ids
                ]
        except Exception:
            pass

        return {"company": company, "allowed_companies": allowed_companies}

    # =========================================================================
    # REQUEST PARSING
    # =========================================================================

    def _parse_json_data(self):
        """Parse JSON body from request."""
        try:
            # Try to get JSON from request body
            raw_data = request.httprequest.get_data(cache=False, as_text=True) or "{}"
            return json.loads(raw_data)
        except Exception as exc:
            _logger.warning("Invalid JSON payload: %s", exc)
            raise ValidationError(_("Invalid JSON payload.")) from exc

    def _get_param(self, key, default=None, cast=None):
        """Get parameter from query string or JSON body."""
        value = request.params.get(key, default)
        if cast and value is not None:
            try:
                value = cast(value)
            except (ValueError, TypeError):
                pass
        return value

    # =========================================================================
    # AUTHENTICATION (SESSION-BASED - NO TOKENS!)
    # =========================================================================

    def _ensure_authenticated(self):
        """
        Ensure user is authenticated via Odoo session.
        Raises AccessDenied if not logged in.
        """
        if not request.session.uid:
            raise AccessDenied(_("Please login first. Use POST /api/v1/auth/login"))
        
        user = request.env['res.users'].browse(request.session.uid)
        if not user or not user.active:
            raise AccessDenied(_("Your account is inactive."))
        
        return request.env

    # =========================================================================
    # ROUTE HANDLER - Works for BOTH type="http" AND type="json" routes
    # =========================================================================

    def _handle_route(self, handler):
        """
        Universal route handler for all route types.
        Always returns proper JSON response.
        """
        try:
            env = self._ensure_authenticated()
            result = handler(env)
            if isinstance(result, Response):
                return result
            # For type="json" routes, Odoo wraps the result automatically
            # For type="http" routes, we need to make a JSON response
            if hasattr(request, 'make_json_response'):
                return request.make_json_response(result)
            return result
        except AccessDenied as exc:
            return request.make_json_response(
                {"success": False, "error": str(exc) or "Unauthorized.", "code": 401},
                status=401,
            )
        except ValidationError as exc:
            return request.make_json_response(
                {"success": False, "error": str(exc), "code": 400},
                status=400,
            )
        except MissingError as exc:
            return request.make_json_response(
                {"success": False, "error": str(exc), "code": 404},
                status=404,
            )
        except Exception as exc:
            _logger.exception("API request failed: %s", exc)
            return request.make_json_response(
                {"success": False, "error": "Internal server error. Check server logs.", "code": 500},
                status=500,
            )


def api_route(route, methods=None, auth="public", csrf=False):
    """Decorator for API routes."""
    if methods is None:
        methods = ["GET"]
    
    def decorator(func):
        @wraps(func)
        def wrapper(self, **kwargs):
            return func(self, **kwargs)
        return wrapper
    return decorator