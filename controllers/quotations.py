from odoo import http, fields, _  
from odoo.http import request
from odoo.exceptions import MissingError, ValidationError
from .common import HavanoApiControllerMixin

import logging
_logger = logging.getLogger(__name__)

class HavanoQuotationsController(HavanoApiControllerMixin, http.Controller):
    
    @http.route("/api/v1/quotations", auth="public", methods=["POST"], type="json", csrf=False)
    def create_quotation(self, **kwargs):
        """POST /api/v1/quotations - Create quotation (draft sales order)."""
        return self._handle_route(lambda env: self._create_quotation(env))
    
    def _create_quotation(self, env):
        data = self._parse_json_data()
        
        partner_id = data.get("partner_id")
        if not partner_id:
            raise ValidationError(_("partner_id is required."))
        
        partner = env["res.partner"].browse(int(partner_id))
        if not partner.exists():
            raise ValidationError(_("Customer #%s not found.") % partner_id)
        
        vals = {
            "partner_id": partner.id,
            "state": "draft",
        }
        
        if data.get("validity_date"):
            vals["validity_date"] = data["validity_date"]
        if data.get("date_order"):
            vals["date_order"] = data["date_order"]
        if data.get("note"):
            vals["note"] = data["note"]
        
        lines = data.get("lines", [])
        if lines:
            order_lines = []
            for line_data in lines:
                product_id = line_data.get("product_id")
                if not product_id:
                    continue
                
                product = env["product.product"].browse(int(product_id))
                if not product.exists():
                    continue
                
                qty = float(line_data.get("quantity", 1))
                price = float(line_data.get("price_unit", product.lst_price))
                
                order_lines.append((0, 0, {
                    "product_id": product.id,
                    "name": line_data.get("name") or product.name,
                    "product_uom_qty": qty,
                    "price_unit": price,
                }))
            
            vals["order_line"] = order_lines
        
        order = env["sale.order"].create(vals)
        
        _logger.info("Quotation created: id=%s, partner=%s", order.id, partner.name)
        
        return self._success({
            "id": order.id,
            "name": order.name,
            "state": order.state,
            "partner_id": order.partner_id.id,
            "partner_name": order.partner_id.name,
            "amount_total": order.amount_total,
        }, message=_("Quotation created."), status=201)
    
    @http.route("/api/v1/quotations/<int:quotation_id>/send", auth="public", methods=["POST"], type="json", csrf=False)
    def send_quotation(self, quotation_id, **kwargs):
        """POST /api/v1/quotations/:id/send - Send quotation by email."""
        return self._handle_route(lambda env: self._send_quotation(env, quotation_id))
    
    def _send_quotation(self, env, quotation_id):
        order = env["sale.order"].browse(quotation_id)
        if not order.exists():
            raise MissingError(_("Quotation #%s not found.") % quotation_id)
        
        if order.state != "draft":
            raise ValidationError(_("Only draft quotations can be sent."))
        
        order.action_quotation_send()
        
        return self._success(message=_("Quotation sent to %s.") % order.partner_id.email)