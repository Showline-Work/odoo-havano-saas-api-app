from odoo import http, fields, _  
from odoo.http import request
from odoo.exceptions import ValidationError
from .common import HavanoApiControllerMixin

import logging
_logger = logging.getLogger(__name__)

class HavanoCustomersController(HavanoApiControllerMixin, http.Controller):
    
    def _safe_get(self, obj, field, default=""):
        """Safely get a field value, returning default if field doesn't exist."""
        try:
            if field in obj._fields:
                val = obj[field]
                return val if val else default
            return default
        except:
            return default
    
    def _serialize_customer(self, partner):
        """Convert res.partner to API response dict with POS-relevant fields."""
        has_mobile = "mobile" in partner._fields
        
        return {
            # === BASIC INFO ===
            "id": partner.id,
            "name": partner.name or "",
            "display_name": partner.display_name or "",
            
            # === TYPE ===
            "company_type": partner.company_type or "person",
            "is_company": partner.is_company,
            
            # === CONTACT INFO ===
            "email": partner.email or "",
            "phone": partner.phone or "",
            "mobile": (partner.mobile or "") if has_mobile else "",
            "website": self._safe_get(partner, "website"),
            
            # === ADDRESS ===
            "street": partner.street or "",
            "street2": partner.street2 or "",
            "city": partner.city or "",
            "zip": partner.zip or "",
            "state_id": partner.state_id.id if partner.state_id else None,
            "state_name": partner.state_id.name or "",
            "country_id": partner.country_id.id if partner.country_id else None,
            "country_name": partner.country_id.name or "",
            "country_code": partner.country_id.code or "",
            
            # === TAX ===
            "vat": partner.vat or "",
            
            # === CUSTOMER RANKING ===
            "customer_rank": partner.customer_rank,
            "supplier_rank": partner.supplier_rank,
            
            # === STATUS ===
            "active": partner.active,
            
            # === LANGUAGE ===
            "lang": partner.lang or "",
            
            # === IMAGE ===
            "has_image": bool(partner.image_1920),
            
            # === NOTES ===
            "comment": self._safe_get(partner, "comment"),
            
            # === PARENT/COMPANY ===
            "parent_id": partner.parent_id.id if partner.parent_id else None,
            "parent_name": partner.parent_id.name or "",
            "company_id": partner.company_id.id if partner.company_id else None,
            "company_name": partner.company_id.name or "",
            
            # === SALES STATS ===
            "sale_order_count": self._safe_get(partner, "sale_order_count", 0),
            "total_invoiced": self._safe_get(partner, "total_invoiced", 0.0),
            
            # === CREDIT ===
            "credit_limit": self._safe_get(partner, "credit_limit", 0.0),
            
            # === WARNINGS ===
            "sale_warn": self._safe_get(partner, "sale_warn", "no"),
            "sale_warn_msg": self._safe_get(partner, "sale_warn_msg"),
            
            # === PRICELIST ===
            "property_product_pricelist": partner.property_product_pricelist.id if partner.property_product_pricelist else None,
            "property_product_pricelist_name": partner.property_product_pricelist.name if partner.property_product_pricelist else "",
            
            # === DATES ===
            "create_date": str(partner.create_date) if partner.create_date else None,
            "write_date": str(partner.write_date) if partner.write_date else None,
        }
    
    @http.route("/api/v1/customers", auth="public", methods=["GET", "POST"], type="http", csrf=False)
    def list_customers(self, limit=100, offset=0, **kwargs):
        """GET /api/v1/customers - List all customers."""
        if request.httprequest.method == "POST":
            return self._handle_route(lambda env: self._upsert_customer(env))
        return self._handle_route(lambda env: self._list_customers(env, limit, offset))
    
    def _list_customers(self, env, limit, offset):
        try:
            limit = min(int(limit), 500)
            offset = int(offset) if offset else 0
        except (ValueError, TypeError):
            limit, offset = 100, 0
        
        domain = [("customer_rank", ">", 0)]
        partners = env["res.partner"].search(domain, limit=limit, offset=offset, order="id desc")
        items = [self._serialize_customer(p) for p in partners]
        total = env["res.partner"].search_count(domain)
        
        return self._success({
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    
    def _upsert_customer(self, env):
        data = self._parse_json_data()
        
        if not data.get("name"):
            raise ValidationError(_("Customer name is required."))
        
        partner = env["res.partner"].browse()
        
        if data.get("email"):
            partner = env["res.partner"].search([
                ("email", "=", data["email"].strip().lower()),
                ("customer_rank", ">", 0),
            ], limit=1)
        
        if not partner and data.get("phone"):
            partner = env["res.partner"].search([
                ("phone", "=", data["phone"].strip()),
                ("customer_rank", ">", 0),
            ], limit=1)
        
        if partner:
            partner.write(data)
            msg = _("Customer updated.")
            status = 200
        else:
            data.setdefault("customer_rank", 1)
            partner = env["res.partner"].create(data)
            msg = _("Customer created.")
            status = 201
        
        _logger.info("Customer %s: id=%s, name=%s", 
                    "updated" if status == 200 else "created",
                    partner.id, partner.name)
        
        return self._success(self._serialize_customer(partner), message=msg, status=status)
    
    @http.route("/api/v1/customers/<int:customer_id>", auth="public", methods=["GET"], type="http", csrf=False)
    def get_customer(self, customer_id, **kwargs):
        """GET /api/v1/customers/:id - Get single customer."""
        return self._handle_route(lambda env: self._get_customer(env, customer_id))
    
    def _get_customer(self, env, customer_id):
        customer = env["res.partner"].browse(customer_id)
        if not customer.exists():
            raise ValidationError(_("Customer #%s not found.") % customer_id)
        return self._success(self._serialize_customer(customer))
    
    @http.route("/api/v1/customers/search", auth="public", methods=["POST", "GET"], type="http", csrf=False)
    def search_customers(self, **kwargs):
        """POST /api/v1/customers/search - Search customers."""
        return self._handle_route(lambda env: self._search_customers(env))
    
    def _search_customers(self, env):
        data = self._parse_json_data()
        query = data.get("query", "")
        limit = min(data.get("limit", 50), 200)
        
        domain = [("customer_rank", ">", 0)]
        
        if query:
            domain += [
                "|", "|", "|",
                ("name", "ilike", query),
                ("email", "ilike", query),
                ("phone", "ilike", query),
                ("city", "ilike", query),
            ]
        
        partners = env["res.partner"].search(domain, limit=limit)
        
        return self._success({
            "items": [self._serialize_customer(p) for p in partners],
            "total": len(partners),
        })