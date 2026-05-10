from odoo import http, fields, _  
from odoo.http import request
from odoo.exceptions import MissingError, ValidationError
from .common import HavanoApiControllerMixin

import logging
_logger = logging.getLogger(__name__)

class HavanoCreditNotesController(HavanoApiControllerMixin, http.Controller):
    
    @http.route("/api/v1/credit-notes", auth="public", methods=["POST"], type="json", csrf=False)
    def create_credit_note(self, **kwargs):
        """POST /api/v1/credit-notes - Create credit note from invoice."""
        return self._handle_route(lambda env: self._create_credit_note(env))
    
    def _create_credit_note(self, env):
        data = self._parse_json_data()
        
        invoice_id = data.get("invoice_id")
        if not invoice_id:
            raise ValidationError(_("invoice_id is required."))
        
        invoice = env["account.move"].browse(int(invoice_id))
        if not invoice.exists():
            raise MissingError(_("Invoice #%s not found.") % invoice_id)
        
        if invoice.state != "posted":
            raise ValidationError(_("Can only credit note posted invoices."))
        
        # Use Odoo's built-in reversal
        reason = data.get("reason", "Customer return")
        date = data.get("date", False)
        
        reversal = env["account.move.reversal"].create({
            "reason": reason,
            "date": date or fields.Date.today(),
            "journal_id": invoice.journal_id.id,
        })
        
        # Apply reversal
        reversal.with_context(active_model="account.move", active_ids=[invoice.id]).reverse_moves()
        
        credit_note = env["account.move"].search([
            ("reversed_entry_id", "=", invoice.id),
        ], limit=1, order="id desc")
        
        _logger.info("Credit note created: id=%s for invoice id=%s", 
                    credit_note.id if credit_note else "?", invoice.id)
        
        return self._success({
            "credit_note_id": credit_note.id if credit_note else None,
            "invoice_id": invoice.id,
        }, message=_("Credit note created."), status=201)
    
    @http.route("/api/v1/credit-notes", auth="public", methods=["GET"], type="json", csrf=False)
    def list_credit_notes(self, limit=100, **kwargs):
        """GET /api/v1/credit-notes - List credit notes."""
        return self._handle_route(lambda env: self._list_credit_notes(env, limit))
    
    def _list_credit_notes(self, env, limit):
        try:
            limit = min(int(limit), 500)
        except (ValueError, TypeError):
            limit = 100
        
        credit_notes = env["account.move"].search_read(
            domain=[("move_type", "=", "out_refund")],
            fields=["id", "name", "state", "partner_id", "amount_total",
                   "invoice_date", "ref"],
            limit=limit,
            order="id desc",
        )
        
        return self._success({
            "items": credit_notes,
            "total": len(credit_notes),
        })