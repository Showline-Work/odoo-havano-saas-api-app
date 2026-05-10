from odoo import http, fields, _  
from odoo.http import request
from odoo.exceptions import MissingError, ValidationError
from .common import HavanoApiControllerMixin

import logging
_logger = logging.getLogger(__name__)

class HavanoSalesOrdersController(HavanoApiControllerMixin, http.Controller):
    
    def _serialize_order(self, order):
        lines = [{
            "id": line.id,
            "product_id": line.product_id.id,
            "product_name": line.product_id.name,
            "quantity": line.product_uom_qty,
            "price_unit": line.price_unit,
            "subtotal": line.price_subtotal,
            "tax_ids": line.tax_ids.ids,
        } for line in order.order_line]
        
        return {
            "id": order.id,
            "name": order.name,
            "state": order.state,
            "partner_id": order.partner_id.id,
            "partner_name": order.partner_id.name,
            "amount_total": order.amount_total,
            "amount_tax": order.amount_tax,
            "amount_untaxed": order.amount_untaxed,
            "date_order": str(order.date_order) if order.date_order else None,
            "client_order_ref": order.client_order_ref or "",
            "note": order.note or "",
            "lines": lines,
            "line_count": len(lines),
        }
    
    @http.route("/api/v1/sales-orders", auth="public", methods=["GET"], type="json", csrf=False)
    def list_orders(self, limit=100, offset=0, state=None, **kwargs):
        """GET /api/v1/sales-orders - List sales orders."""
        return self._handle_route(lambda env: self._list_orders(env, limit, offset, state))
    
    def _list_orders(self, env, limit, offset, state):
        try:
            limit = min(int(limit), 500)
            offset = int(offset) if offset else 0
        except (ValueError, TypeError):
            limit, offset = 100, 0
        
        domain = []
        if state:
            domain.append(("state", "=", state))
        
        orders = env["sale.order"].search_read(
            domain=domain,
            fields=["id", "name", "state", "partner_id", "amount_total", 
                   "amount_tax", "amount_untaxed", "date_order", 
                   "client_order_ref", "note"],
            limit=limit,
            offset=offset,
            order="id desc",
        )
        
        total = env["sale.order"].search_count(domain)
        
        return self._success({
            "items": orders,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    
    @http.route("/api/v1/sales-orders/<int:order_id>", auth="public", methods=["GET"], type="json", csrf=False)
    def get_order(self, order_id, **kwargs):
        """GET /api/v1/sales-orders/:id - Get single order with lines."""
        return self._handle_route(lambda env: self._get_order(env, order_id))
    
    def _get_order(self, env, order_id):
        order = env["sale.order"].browse(order_id)
        if not order.exists():
            raise MissingError(_("Sales order #%s not found.") % order_id)
        
        return self._success(self._serialize_order(order))
    
    @http.route("/api/v1/sales-orders", auth="public", methods=["POST"], type="json", csrf=False)
    def create_order(self, **kwargs):
        """POST /api/v1/sales-orders - Create sales order."""
        return self._handle_route(lambda env: self._create_order(env))
    
    def _create_order(self, env):
        data = self._parse_json_data()
        
        # Validate partner
        partner_id = data.get("partner_id")
        if not partner_id:
            raise ValidationError(_("partner_id is required."))
        
        partner = env["res.partner"].browse(int(partner_id))
        if not partner.exists():
            raise ValidationError(_("Customer #%s not found.") % partner_id)
        
        # Prepare order values
        vals = {
            "partner_id": partner.id,
            "company_id": env.company.id,
        }
        
        if data.get("client_order_ref"):
            vals["client_order_ref"] = data["client_order_ref"]
        if data.get("note"):
            vals["note"] = data["note"]
        if data.get("date_order"):
            vals["date_order"] = data["date_order"]
        
        # Prepare order lines
        lines = data.get("lines", [])
        if not lines:
            raise ValidationError(_("At least one order line is required."))
        
        order_lines = []
        for line_data in lines:
            product_id = line_data.get("product_id")
            if not product_id:
                raise ValidationError(_("product_id is required for each line."))
            
            product = env["product.product"].browse(int(product_id))
            if not product.exists():
                raise ValidationError(_("Product #%s not found.") % product_id)
            
            qty = float(line_data.get("quantity", 1))
            if qty <= 0:
                raise ValidationError(_("Quantity must be positive."))
            
            price = float(line_data.get("price_unit", product.lst_price))
            
            # Handle taxes
            tax_ids = line_data.get("tax_ids", [])
            if not tax_ids:
                tax_ids = product.taxes_id.ids
            
            order_lines.append((0, 0, {
                "product_id": product.id,
                "name": line_data.get("name") or product.name,
                "product_uom_qty": qty,
                "price_unit": price,
                "tax_ids": [(6, 0, tax_ids)],
            }))
        
        vals["order_line"] = order_lines
        
        # Create order
        order = env["sale.order"].create(vals)
        
        _logger.info("Sales order created: id=%s, partner=%s, total=%s",
                    order.id, partner.name, order.amount_total)
        
        return self._success(self._serialize_order(order), 
                           message=_("Sales order created."), status=201)
    
    @http.route("/api/v1/sales-orders/<int:order_id>/confirm", auth="public", methods=["POST"], type="json", csrf=False)
    def confirm_order(self, order_id, **kwargs):
        """POST /api/v1/sales-orders/:id/confirm - Confirm sales order."""
        return self._handle_route(lambda env: self._confirm_order(env, order_id))
    
    def _confirm_order(self, env, order_id):
        order = env["sale.order"].browse(order_id)
        if not order.exists():
            raise MissingError(_("Sales order #%s not found.") % order_id)
        
        if order.state in ("sale", "done"):
            return self._success(self._serialize_order(order), 
                               message=_("Order already confirmed."))
        
        order.action_confirm()
        
        _logger.info("Sales order confirmed: id=%s, name=%s", order.id, order.name)
        
        return self._success(self._serialize_order(order), 
                           message=_("Sales order confirmed."))
    
    @http.route("/api/v1/sales-orders/<int:order_id>/cancel", auth="public", methods=["POST"], type="json", csrf=False)
    def cancel_order(self, order_id, **kwargs):
        """POST /api/v1/sales-orders/:id/cancel - Cancel sales order."""
        return self._handle_route(lambda env: self._cancel_order(env, order_id))
    
    def _cancel_order(self, env, order_id):
        order = env["sale.order"].browse(order_id)
        if not order.exists():
            raise MissingError(_("Sales order #%s not found.") % order_id)
        
        if order.state == "cancel":
            return self._success(self._serialize_order(order), 
                               message=_("Order already cancelled."))
        
        order.action_cancel()
        
        _logger.info("Sales order cancelled: id=%s, name=%s", order.id, order.name)
        
        return self._success(self._serialize_order(order), 
                           message=_("Sales order cancelled."))