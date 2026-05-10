from odoo import http, _
from odoo.http import request
from odoo.exceptions import MissingError, ValidationError
from .common import HavanoApiControllerMixin

import logging
_logger = logging.getLogger(__name__)

class HavanoInvoicesController(HavanoApiControllerMixin, http.Controller):
    
    def _serialize_invoice(self, move):
        return {
            "id": move.id,
            "name": move.name or "",
            "state": move.state,
            "move_type": move.move_type,
            "partner_id": move.partner_id.id,
            "partner_name": move.partner_id.name,
            "amount_total": move.amount_total,
            "amount_tax": move.amount_tax,
            "amount_untaxed": move.amount_untaxed,
            "amount_residual": move.amount_residual,
            "invoice_date": str(move.invoice_date) if move.invoice_date else None,
            "invoice_date_due": str(move.invoice_date_due) if move.invoice_date_due else None,
            "payment_state": move.payment_state,
            "ref": move.ref or "",
            "narration": move.narration or "",
        }
    
    @http.route("/api/v1/invoices", auth="public", methods=["GET"], type="json", csrf=False)
    def list_invoices(self, limit=100, offset=0, state=None, **kwargs):
        """GET /api/v1/invoices - List invoices."""
        return self._handle_route(lambda env: self._list_invoices(env, limit, offset, state))
    
    def _list_invoices(self, env, limit, offset, state):
        try:
            limit = min(int(limit), 500)
            offset = int(offset) if offset else 0
        except (ValueError, TypeError):
            limit, offset = 100, 0
        
        domain = [("move_type", "=", "out_invoice")]
        if state:
            domain.append(("state", "=", state))
        
        invoices = env["account.move"].search_read(
            domain=domain,
            fields=["id", "name", "state", "move_type", "partner_id", 
                   "amount_total", "amount_tax", "amount_untaxed",
                   "amount_residual", "invoice_date", "invoice_date_due",
                   "payment_state", "ref", "narration"],
            limit=limit,
            offset=offset,
            order="id desc",
        )
        
        total = env["account.move"].search_count(domain)
        
        return self._success({
            "items": invoices,
            "total": total,
        })
    
    @http.route("/api/v1/invoices", auth="public", methods=["POST"], type="json", csrf=False)
    def create_invoice(self, **kwargs):
        """POST /api/v1/invoices - Create invoice."""
        return self._handle_route(lambda env: self._create_invoice(env))
    
    def _create_invoice(self, env):
        data = self._parse_json_data()
        
        partner_id = data.get("partner_id")
        if not partner_id:
            raise ValidationError(_("partner_id is required."))
        
        partner = env["res.partner"].browse(int(partner_id))
        if not partner.exists():
            raise ValidationError(_("Customer #%s not found.") % partner_id)
        
        lines = data.get("lines", [])
        if not lines:
            raise ValidationError(_("At least one invoice line is required."))
        
        invoice_lines = []
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
            
            # Get income account
            account = product.property_account_income_id or product.categ_id.property_account_income_categ_id
            if not account:
                raise ValidationError(_("No income account found for product '%s'.") % product.name)
            
            tax_ids = line_data.get("tax_ids", product.taxes_id.ids)
            
            invoice_lines.append((0, 0, {
                "product_id": product.id,
                "name": line_data.get("name") or product.name,
                "quantity": qty,
                "price_unit": price,
                "account_id": account.id,
                "tax_ids": [(6, 0, tax_ids)],
            }))
        
        vals = {
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "invoice_line_ids": invoice_lines,
            "company_id": env.company.id,
        }
        
        if data.get("invoice_date"):
            vals["invoice_date"] = data["invoice_date"]
        if data.get("invoice_date_due"):
            vals["invoice_date_due"] = data["invoice_date_due"]
        if data.get("ref"):
            vals["ref"] = data["ref"]
        if data.get("narration"):
            vals["narration"] = data["narration"]
        
        move = env["account.move"].create(vals)
        
        _logger.info("Invoice created: id=%s, partner=%s, total=%s",
                    move.id, partner.name, move.amount_total)
        
        return self._success(self._serialize_invoice(move), 
                           message=_("Invoice created."), status=201)
    
    @http.route("/api/v1/invoices/<int:invoice_id>/post", auth="public", methods=["POST"], type="json", csrf=False)
    def post_invoice(self, invoice_id, **kwargs):
        """POST /api/v1/invoices/:id/post - Post invoice."""
        return self._handle_route(lambda env: self._post_invoice(env, invoice_id))
    
    def _post_invoice(self, env, invoice_id):
        move = env["account.move"].browse(invoice_id)
        if not move.exists():
            raise MissingError(_("Invoice #%s not found.") % invoice_id)
        
        if move.state == "posted":
            return self._success(self._serialize_invoice(move), 
                               message=_("Invoice already posted."))
        
        move.action_post()
        
        _logger.info("Invoice posted: id=%s, name=%s", move.id, move.name)
        
        return self._success(self._serialize_invoice(move), 
                           message=_("Invoice posted."))