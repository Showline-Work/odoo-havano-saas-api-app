from odoo import http, fields, _  
from odoo.http import request
from .common import HavanoApiControllerMixin

class HavanoPaymentsController(HavanoApiControllerMixin, http.Controller):
    
    @http.route("/api/v1/payments/overdue", auth="public", methods=["GET", "POST"], type="json", csrf=False)
    def get_overdue_payments(self, limit=100, **kwargs):
        """GET /api/v1/payments/overdue - Get overdue invoices."""
        return self._handle_route(lambda env: self._get_overdue(env, limit))
    
    def _get_overdue(self, env, limit):
        try:
            limit = min(int(limit), 500)
        except (ValueError, TypeError):
            limit = 100
        
        from datetime import date
        today = date.today()
        
        overdue = env["account.move"].search_read(
            domain=[
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("payment_state", "!=", "paid"),
                ("invoice_date_due", "<", today),
            ],
            fields=["id", "name", "partner_id", "amount_total", 
                   "amount_residual", "invoice_date_due", "payment_state"],
            limit=limit,
            order="invoice_date_due asc",
        )
        
        total_overdue = sum(inv.get("amount_residual", 0) for inv in overdue)
        
        return self._success({
            "items": overdue,
            "total": len(overdue),
            "total_amount_overdue": total_overdue,
        })
    
    @http.route("/api/v1/payments", auth="public", methods=["POST"], type="json", csrf=False)
    def register_payment(self, **kwargs):
        """POST /api/v1/payments - Register payment for invoice."""
        return self._handle_route(lambda env: self._register_payment(env))
    
    def _register_payment(self, env):
        data = self._parse_json_data()
        
        invoice_id = data.get("invoice_id")
        amount = data.get("amount")
        payment_date = data.get("payment_date")
        
        if not invoice_id or not amount:
            return self._error("invoice_id and amount are required.", code=400)
        
        invoice = env["account.move"].browse(int(invoice_id))
        if not invoice.exists():
            return self._error(f"Invoice #{invoice_id} not found.", code=404)
        
        # Create payment
        payment_method = env.ref("account.account_payment_method_manual_in", raise_if_not_found=False)
        journal = env["account.journal"].search([("type", "in", ["bank", "cash"])], limit=1)
        
        payment = env["account.payment"].create({
            "payment_type": "inbound",
            "partner_id": invoice.partner_id.id,
            "amount": float(amount),
            "date": payment_date or fields.Date.today(),
            "journal_id": journal.id,
            "payment_method_id": payment_method.id,
            "ref": f"Payment for {invoice.name}",
        })
        
        payment.action_post()
        
        # Reconcile
        (payment.line_ids + invoice.line_ids).reconcile()
        
        return self._success({
            "payment_id": payment.id,
            "invoice_id": invoice.id,
            "amount": float(amount),
        }, message=_("Payment registered and reconciled."))