from odoo import http, fields, _
from odoo.http import request
from odoo.exceptions import ValidationError
from .common import HavanoApiControllerMixin

import logging
_logger = logging.getLogger(__name__)


class HavanoSalesController(HavanoApiControllerMixin, http.Controller):
    """
    POS Sales Controller
    
    Receives finalized POS transactions and records them in Odoo.
    The POS handles all sale computation - Odoo only records.
    
    Flow:
    1. Validate payload
    2. Check for duplicate (by pos_reference)
    3. Create Customer Invoice (account.move)
    4. Post Invoice
    5. Register Payments
    6. Reconcile Payments with Invoice
    7. Return success response
    """
    
    @http.route("/api/v1/sales", auth="public", methods=["POST"], type="http", csrf=False)
    def process_pos_sale(self, **kwargs):
        """
        POST /api/v1/sales
        
        Process a complete POS sale: create invoice, register payments, reconcile.
        
        Request Body:
        {
            "pos_reference": "POS-1001",
            "customer_id": 7,
            "customer_name": "John Doe",       # Optional - for walk-in customers
            "lines": [
                {
                    "product_id": 45,
                    "quantity": 2,
                    "price_unit": 10.00,
                    "tax_ids": [1]
                }
            ],
            "payments": [
                {
                    "amount": 20.00,
                    "method": "cash"
                }
            ],
            "date_order": "2026-04-29"          # Optional - defaults to today
        }
        """
        return self._handle_route(lambda env: self._process_sale(env))
    
    def _process_sale(self, env):
        """Main processing logic"""
        data = self._parse_json_data()
        
        # ================================================================
        # 1. VALIDATION
        # ================================================================
        pos_reference = data.get("pos_reference")
        lines = data.get("lines", [])
        payments = data.get("payments", [])
        
        if not pos_reference:
            raise ValidationError(_("pos_reference is required."))
        
        if not lines:
            raise ValidationError(_("At least one sale line is required."))
        
        _logger.info("Processing POS sale: %s with %s lines and %s payments",
                    pos_reference, len(lines), len(payments))
        
        # ================================================================
        # 2. DUPLICATE PROTECTION
        # ================================================================
        existing_invoice = env["account.move"].sudo().search([
            ("ref", "=", pos_reference),
            ("move_type", "=", "out_invoice"),
        ], limit=1)
        
        if existing_invoice:
            _logger.info("Duplicate POS sale detected: %s (invoice #%s)", 
                        pos_reference, existing_invoice.name)
            return self._success({
                "invoice_id": existing_invoice.id,
                "invoice_name": existing_invoice.name,
                "amount_total": existing_invoice.amount_total,
                "payment_state": existing_invoice.payment_state,
                "state": existing_invoice.state,
                "duplicate": True,
            }, message=_("Sale already processed. Existing invoice #%s.") % existing_invoice.name)
        
        # ================================================================
        # 3. RESOLVE CUSTOMER
        # ================================================================
        partner = self._resolve_partner(env, data)
        
        # ================================================================
        # 4. CREATE INVOICE
        # ================================================================
        invoice = self._create_invoice(env, partner, pos_reference, lines, data)
        
        # ================================================================
        # 5. POST INVOICE
        # ================================================================
        invoice.action_post()
        _logger.info("Invoice posted: %s (id=%s)", invoice.name, invoice.id)
        
        # ================================================================
        # 6. REGISTER PAYMENTS & RECONCILE
        # ================================================================
        for payment_data in payments:
            self._register_payment(env, invoice, payment_data, pos_reference)
        
        # Refresh invoice state after payments
        invoice.invalidate_recordset()
        
        # ================================================================
        # 7. RETURN SUCCESS
        # ================================================================
        return self._success({
            "invoice_id": invoice.id,
            "invoice_name": invoice.name,
            "amount_total": invoice.amount_total,
            "amount_residual": invoice.amount_residual,
            "payment_state": invoice.payment_state,
            "state": invoice.state,
            "partner_id": partner.id,
            "partner_name": partner.name,
        }, message=_("Sale processed successfully."), status=201)
    
    # ================================================================
    # HELPER METHODS
    # ================================================================
    
    def _resolve_partner(self, env, data):
        """
        Resolve the customer for the sale.
        
        Priority:
        1. customer_id - existing Odoo partner
        2. customer_name - create or find walk-in customer
        3. Default to a generic "POS Customer"
        """
        partner_model = env["res.partner"].sudo()
        
        # Option 1: Specific customer ID
        customer_id = data.get("customer_id")
        if customer_id:
            partner = partner_model.browse(int(customer_id))
            if partner.exists():
                _logger.info("Using existing customer: %s (id=%s)", partner.name, partner.id)
                return partner
        
        # Option 2: Customer name provided (walk-in)
        customer_name = data.get("customer_name", "").strip()
        if customer_name:
            # Search by name or create
            partner = partner_model.search([
                ("name", "=", customer_name),
                ("customer_rank", ">", 0),
            ], limit=1)
            
            if partner:
                _logger.info("Found walk-in customer: %s (id=%s)", partner.name, partner.id)
                return partner
            
            # Create new walk-in customer
            partner = partner_model.create({
                "name": customer_name,
                "customer_rank": 1,
            })
            _logger.info("Created walk-in customer: %s (id=%s)", partner.name, partner.id)
            return partner
        
        # Option 3: Generic POS Customer
        partner = partner_model.search([
            ("name", "=", "POS Customer"),
        ], limit=1)
        
        if not partner:
            partner = partner_model.create({
                "name": "POS Customer",
                "customer_rank": 1,
            })
            _logger.info("Created default POS Customer (id=%s)", partner.id)
        
        return partner
    
    def _create_invoice(self, env, partner, pos_reference, lines, data):
        """
        Create and return a posted customer invoice.
        
        :param env: Odoo environment
        :param partner: res.partner record
        :param pos_reference: unique POS reference
        :param lines: list of line dicts
        :param data: full request payload
        :return: account.move record
        """
        move_model = env["account.move"].sudo()
        
        # Prepare invoice lines
        invoice_lines = []
        for line_data in lines:
            product_id = line_data.get("product_id")
            if not product_id:
                raise ValidationError(_("product_id is required for each line."))
            
            product = env["product.product"].sudo().browse(int(product_id))
            if not product.exists():
                raise ValidationError(_("Product #%s not found.") % product_id)
            
            quantity = float(line_data.get("quantity", 1))
            if quantity <= 0:
                raise ValidationError(_("Quantity must be positive for product '%s'.") % product.name)
            
            price_unit = float(line_data.get("price_unit", product.lst_price))
            
            # Get income account
            account = (
                product.property_account_income_id 
                or product.categ_id.property_account_income_categ_id
            )
            if not account:
                raise ValidationError(
                    _("No income account found for product '%s'. Please configure it.") 
                    % product.name
                )
            
            # Resolve taxes
            tax_ids = line_data.get("tax_ids", [])
            if not tax_ids:
                # Use product's default sale taxes
                tax_ids = product.taxes_id.filtered(
                    lambda t: t.type_tax_use == "sale"
                ).ids
            
            invoice_lines.append((0, 0, {
                "product_id": product.id,
                "name": line_data.get("name") or product.display_name,
                "quantity": quantity,
                "price_unit": price_unit,
                "account_id": account.id,
                "tax_ids": [(6, 0, tax_ids)],
            }))
        
        # Get or find a sales journal
        journal = env["account.journal"].sudo().search([
            ("type", "=", "sale"),
            ("company_id", "=", env.company.id),
        ], limit=1)
        
        if not journal:
            raise ValidationError(_("No sales journal found. Please configure one in Accounting."))
        
        # Create invoice
        invoice_vals = {
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "ref": pos_reference,
            "invoice_line_ids": invoice_lines,
            "journal_id": journal.id,
            "company_id": env.company.id,
            "invoice_date": data.get("date_order") or fields.Date.today(),
            "narration": data.get("note", ""),
        }
        
        invoice = move_model.create(invoice_vals)
        _logger.info("Invoice created: %s (id=%s) for partner %s, total=%s",
                    invoice.name, invoice.id, partner.name, invoice.amount_total)
        
        return invoice
    
    def _register_payment(self, env, invoice, payment_data, pos_reference):
        """Create and post a payment, then reconcile with the invoice."""
        Payment = env["account.payment"].sudo()
        
        amount = float(payment_data.get("amount", 0))
        if amount <= 0:
            _logger.warning("Skipping payment with amount <= 0: %s", amount)
            return
        
        method = payment_data.get("method", "cash").lower()
        
        # Find appropriate journal based on payment method
        journal = self._get_payment_journal(env, method)
        
        # Find payment method line
        payment_method_line = self._get_payment_method_line(env, journal, method)
        
        # FIX: Odoo Community uses 'memo', not 'ref'
        payment = Payment.create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": invoice.partner_id.id,
            "amount": amount,
            "journal_id": journal.id,
            "payment_method_line_id": payment_method_line.id if payment_method_line else False,
            "date": fields.Date.today(),
            "memo": f"{pos_reference} - {method.title()} Payment",
        })
        
        # Post the payment
        payment.action_post()
        _logger.info("Payment posted: id=%s, amount=%s, method=%s", 
                    payment.id, amount, method)
        
        # Reconcile payment with invoice
        self._reconcile_payment(env, invoice, payment)

    def _get_payment_journal(self, env, method):
        """Find appropriate journal for the payment method."""
        Journal = env["account.journal"].sudo()
        
        # FIX: Odoo uses 'bank' and 'cash' types, not 'cash' directly sometimes
        if method == "cash":
            journal = Journal.search([
                ("type", "=", "cash"),
                ("company_id", "=", env.company.id),
            ], limit=1)
            if not journal:
                # Fallback to bank type if no cash journal
                journal = Journal.search([
                    ("type", "=", "bank"),
                    ("company_id", "=", env.company.id),
                ], limit=1)
        else:
            # Card, bank, or other electronic
            journal = Journal.search([
                ("type", "=", "bank"),
                ("company_id", "=", env.company.id),
            ], limit=1)
        
        if not journal:
            # Fallback to any bank or cash journal
            journal = Journal.search([
                ("type", "in", ["bank", "cash"]),
                ("company_id", "=", env.company.id),
            ], limit=1)
        
        if not journal:
            raise ValidationError(_(
                "No cash or bank journal found. Please configure one in Accounting."
            ))
        
        return journal
    
    def _get_payment_method_line(self, env, journal, method):
        """
        Find appropriate payment method line for the journal.
        
        :param journal: account.journal record
        :param method: payment method string
        :return: account.payment.method.line record or None
        """
        PaymentMethodLine = env["account.payment.method.line"].sudo()
        
        # Get inbound payment method lines for this journal
        lines = journal.inbound_payment_method_line_ids
        
        if not lines:
            # Search for any manual inbound payment method
            payment_method = env.ref(
                "account.account_payment_method_manual_in", 
                raise_if_not_found=False
            )
            if payment_method:
                lines = PaymentMethodLine.search([
                    ("payment_method_id", "=", payment_method.id),
                    ("journal_id", "=", journal.id),
                ], limit=1)
        
        return lines[:1] if lines else None
    
    def _reconcile_payment(self, env, invoice, payment):
        """
        Reconcile payment lines with invoice lines.
        """
        # Get ALL receivable/payable lines from payment move
        payment_lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id.account_type in ('asset_receivable', 'liability_payable')
            and not line.reconciled
        )
        
        # Get ALL receivable/payable lines from invoice
        invoice_lines = invoice.line_ids.filtered(
            lambda line: line.account_id.account_type in ('asset_receivable', 'liability_payable')
            and not line.reconciled
        )
        
        _logger.info("Reconciliation: payment_lines=%s, invoice_lines=%s",
                    payment_lines.ids, invoice_lines.ids)
        
        if payment_lines and invoice_lines:
            # Reconcile them together
            (payment_lines + invoice_lines).reconcile()
            
            # Refresh invoice state
            invoice.invalidate_recordset(['payment_state', 'amount_residual'])
            
            _logger.info("Payment reconciled with invoice %s. Payment state: %s, Residual: %s",
                        invoice.name, invoice.payment_state, invoice.amount_residual)
        else:
            _logger.warning("Could not reconcile: payment_lines=%s, invoice_lines=%s",
                        bool(payment_lines), bool(invoice_lines))