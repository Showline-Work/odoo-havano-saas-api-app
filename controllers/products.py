from odoo import http, fields, _  
from odoo.http import request
from odoo.exceptions import MissingError, ValidationError
from .common import HavanoApiControllerMixin

import logging
_logger = logging.getLogger(__name__)

class HavanoProductsController(HavanoApiControllerMixin, http.Controller):
    
    def _get_lot_serial_info(self, product_variant):
        """Get lot/serial number information for a product variant."""
        lots = []
        try:
            quant_model = product_variant.env["stock.quant"]
            quants = quant_model.search([
                ("product_id", "=", product_variant.id),
                ("lot_id", "!=", False),
            ])
            for quant in quants:
                lot = quant.lot_id
                lots.append({
                    "lot_id": lot.id,
                    "lot_name": lot.name,
                    "quantity": quant.quantity,
                    "reserved_quantity": quant.reserved_quantity,
                    "expiration_date": str(lot.expiration_date) if hasattr(lot, 'expiration_date') and lot.expiration_date else None,
                    "use_date": str(lot.use_date) if hasattr(lot, 'use_date') and lot.use_date else None,
                    "removal_date": str(lot.removal_date) if hasattr(lot, 'removal_date') and lot.removal_date else None,
                })
        except Exception as e:
            _logger.exception("Could not fetch lot info for variant %s: %s", product_variant.id if product_variant else "n/a", str(e))
        return lots
    
    def _serialize_product(self, product):
        """Convert product.template to API response dict."""
        _logger.debug("Serializing product template id=%s name=%s", product.id, product.name)
        has_detailed_type = "detailed_type" in product._fields
        
        taxes = product.taxes_id
        supplier_taxes = product.supplier_taxes_id
        
        main_variant = product.product_variant_id
        
        variants = []
        for variant in product.product_variant_ids:
            variants.append({
                "id": variant.id,
                "default_code": variant.default_code or "",
                "barcode": variant.barcode or "",
                "lst_price": variant.lst_price,
                "standard_price": variant.standard_price,
                "active": variant.active,
                "tracking": variant.tracking if hasattr(variant, 'tracking') else "none",
                "qty_available": variant.qty_available,
                "lots_serials": self._get_lot_serial_info(variant),
                "attributes": [{
                    "attribute_id": ptav.attribute_id.id,
                    "attribute_name": ptav.attribute_id.name,
                    "value_id": ptav.id,
                    "value_name": ptav.name,
                    "price_extra": ptav.price_extra,
                } for ptav in variant.product_template_attribute_value_ids],
            })
        
        suppliers = []
        for seller in product.seller_ids:
            suppliers.append({
                "id": seller.id,
                "partner_id": seller.partner_id.id,
                "partner_name": seller.partner_id.name,
                "product_code": seller.product_code or "",
                "product_name": seller.product_name or "",
                "price": seller.price,
                "discount": seller.discount,
                "currency_id": seller.currency_id.id,
                "currency_name": seller.currency_id.name,
                "date_start": str(seller.date_start) if seller.date_start else None,
                "date_end": str(seller.date_end) if seller.date_end else None,
            })
        
        pricelist_rules = []
        for rule in product.pricelist_rule_ids:
            pricelist_rules.append({
                "id": rule.id,
                "pricelist_id": rule.pricelist_id.id,
                "pricelist_name": rule.pricelist_id.name,
                "applied_on": rule.applied_on,
                "compute_price": rule.compute_price,
                "fixed_price": rule.fixed_price,
                "percent_price": rule.percent_price,
                "price_discount": rule.price_discount,
                "price_surcharge": rule.price_surcharge,
                "price_round": rule.price_round,
                "price_markup": rule.price_markup,
                "price_min_margin": rule.price_min_margin,
                "price_max_margin": rule.price_max_margin,
                "min_quantity": rule.min_quantity,
                "date_start": str(rule.date_start) if rule.date_start else None,
                "date_end": str(rule.date_end) if rule.date_end else None,
            })
        
        packagings = []
        for uom_line in product.uom_ids:
            packagings.append({
                "id": uom_line.id,
                "name": uom_line.name,
                "barcode": uom_line.barcode if hasattr(uom_line, 'barcode') else "",
            })
        
        warehouse_stock = []
        try:
            warehouses = product.env["stock.warehouse"].search([])
            for wh in warehouses:
                all_locs = product.env["stock.location"].search([
                    ("id", "child_of", wh.view_location_id.id),
                ])
                
                quants = product.env["stock.quant"].search([
                    ("product_id", "in", product.product_variant_ids.ids),
                    ("location_id", "in", all_locs.ids),
                ])
                
                total = sum(quants.mapped("quantity"))
                reserved = sum(quants.mapped("reserved_quantity"))
                
                warehouse_stock.append({
                    "warehouse_id": wh.id,
                    "warehouse_name": wh.name,
                    "warehouse_code": wh.code,
                    "qty_available": total,
                    "reserved": reserved,
                    "available": total - reserved,
                })
        except Exception as e:
            _logger.exception("Could not fetch warehouse stock for product %s: %s", product.id, str(e))
        
        return {
            "id": product.id,
            "name": product.name or "",
            "display_name": product.display_name,
            "sequence": product.sequence,
            "default_code": product.default_code or "",
            "barcode": product.barcode or "",
            
            "list_price": product.list_price,
            "standard_price": product.standard_price,
            "currency_id": product.currency_id.id,
            "currency_name": product.currency_id.name,
            "cost_currency_id": product.cost_currency_id.id,
            "cost_currency_name": product.cost_currency_id.name,
            
            "active": product.active,
            "product_type": product.detailed_type if has_detailed_type else product.type,
            "service_tracking": product.service_tracking,
            
            "tracking": product.tracking if hasattr(product, 'tracking') else "none",
            "use_expiration_date": product.use_expiration_date if hasattr(product, 'use_expiration_date') else False,
            "expiration_time": product.expiration_time if hasattr(product, 'expiration_time') else 0,
            
            "lots_serials": self._get_lot_serial_info(main_variant) if main_variant else [],
            
            "category": product.categ_id.name or "",
            "category_id": product.categ_id.id,
            "category_complete_name": product.categ_id.complete_name or "",
            
            "uom": {
                "id": product.uom_id.id,
                "name": product.uom_id.name,
                "factor": product.uom_id.factor,
                "rounding": product.uom_id.rounding,
            },
            "uom_id": product.uom_id.id,
            "uom_name": product.uom_name or "",
            "packagings": packagings,
            
            "qty_available": product.qty_available,
            "warehouse_stock": warehouse_stock,
            
            "inventory_availability": product.inventory_availability if hasattr(product, 'inventory_availability') else "never",
            "out_of_stock_message": product.out_of_stock_message if hasattr(product, 'out_of_stock_message') and product.out_of_stock_message else "",
            
            "description": product.description or "",
            "description_sale": product.description_sale or "",
            "description_purchase": product.description_purchase or "",
            
            "tags": [{
                "id": tag.id, "name": tag.name, "color": tag.color,
                "visible_to_customers": tag.visible_to_customers,
            } for tag in product.product_tag_ids],
            
            "taxes": [{
                "id": tax.id, "name": tax.name, "amount": tax.amount,
                "type_tax_use": tax.type_tax_use,
            } for tax in taxes],
            "supplier_taxes": [{
                "id": tax.id, "name": tax.name, "amount": tax.amount,
            } for tax in supplier_taxes],
            
            "has_configurable_attributes": product.has_configurable_attributes,
            "is_dynamically_created": product.is_dynamically_created,
            "variant_count": product.product_variant_count,
            "variant_id": product.product_variant_id.id if product.product_variant_id else False,
            "variants": variants,
            "attribute_lines": [{
                "id": line.id,
                "attribute_id": line.attribute_id.id,
                "attribute_name": line.attribute_id.name,
                "display_type": line.attribute_id.display_type,
                "create_variant": line.attribute_id.create_variant,
                "sequence": line.sequence,
                "values": [{
                    "id": val.id, "name": val.name, "price_extra": val.price_extra,
                    "html_color": val.html_color or "", "is_custom": val.is_custom,
                    "image": val.image.decode() if val.image else None,
                } for val in line.product_template_value_ids],
            } for line in product.attribute_line_ids],
            
            "suppliers": suppliers,
            "pricelist_rules": pricelist_rules,
            
            "company_id": product.company_id.id,
            "company_name": product.company_id.name,
        }
    
    @http.route("/api/v1/products", auth="public", methods=["GET"], type="http", csrf=False)
    def list_products(self, limit=100, offset=0, order="id desc", **kwargs):
        """GET /api/v1/products - List products with pagination."""
        return self._handle_route(lambda env: self._list_products(env, limit, offset, order))
    
    def _list_products(self, env, limit, offset, order):
        try:
            limit = min(int(limit), 500)
            offset = int(offset) if offset else 0
        except (ValueError, TypeError):
            limit, offset = 100, 0
        
        product_model = env["product.template"]
        domain = [("active", "=", True)]
        
        products = product_model.search(domain, limit=limit, offset=offset, order=order)
        items = []
        for p in products:
            try:
                items.append(self._serialize_product(p))
            except Exception as exc:
                _logger.exception("Failed to serialize product id=%s: %s", p.id, str(exc))
        total = product_model.search_count(domain)
        
        return self._success({
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    
    @http.route("/api/v1/products/<int:product_id>", auth="public", methods=["GET"], type="http", csrf=False)
    def get_product(self, product_id, **kwargs):
        """GET /api/v1/products/:id - Get single product with details."""
        return self._handle_route(lambda env: self._get_product(env, product_id))
    
    def _get_product(self, env, product_id):
        product = env["product.template"].browse(product_id)
        if not product.exists():
            raise MissingError(_("Product #%s not found.") % product_id)
        try:
            return self._success(self._serialize_product(product))
        except Exception as exc:
            _logger.exception("Failed to serialize single product id=%s: %s", product.id, str(exc))
            raise
    
    @http.route("/api/v1/products", auth="public", methods=["POST"], type="json", csrf=False)
    def create_product(self, **kwargs):
        """POST /api/v1/products - Create or update product by SKU."""
        return self._handle_route(lambda env: self._upsert_product(env))
    
    def _upsert_product(self, env):
        data = self._parse_json_data()
        sku = data.get("default_code") or data.get("sku")
        
        if not sku:
            raise ValidationError(_("Product SKU (default_code) is required."))
        
        if not data.get("name"):
            data["name"] = sku
        
        if "type" in data:
            data.pop("type")
        
        product = env["product.template"].search([
            ("default_code", "=", str(sku).strip())
        ], limit=1)
        
        if product:
            product.write(data)
            msg = _("Product updated.")
            status = 200
        else:
            data.setdefault("is_storable", True)
            data.setdefault("sale_ok", True)
            data.setdefault("purchase_ok", True)
            product = env["product.template"].create(data)
            msg = _("Product created.")
            status = 201
        
        _logger.info("Product %s: id=%s, sku=%s", "updated" if status == 200 else "created", 
                    product.id, sku)
        
        return self._success(self._serialize_product(product), message=msg, status=status)
    
    @http.route("/api/v1/products/<int:product_id>", auth="public", methods=["PUT", "POST"], type="json", csrf=False)
    def update_product(self, product_id, **kwargs):
        """PUT /api/v1/products/:id - Update product."""
        return self._handle_route(lambda env: self._update_product(env, product_id))
    
    def _update_product(self, env, product_id):
        data = self._parse_json_data()
        product = env["product.template"].browse(product_id)
        if not product.exists():
            raise MissingError(_("Product #%s not found.") % product_id)
        if not data:
            raise ValidationError(_("No data provided for update."))
        product.write(data)
        return self._success(self._serialize_product(product), message=_("Product updated."))

    @http.route("/api/v1/products/<int:product_id>", auth="public", methods=["DELETE"], type="json", csrf=False)
    def delete_product(self, product_id, **kwargs):
        """DELETE /api/v1/products/:id - Archive product."""
        return self._handle_route(lambda env: self._delete_product(env, product_id))

    def _delete_product(self, env, product_id):
        product = env["product.template"].browse(product_id)
        if not product.exists():
            raise MissingError(_("Product #%s not found.") % product_id)
        if not product.active:
            return self._success({"id": product.id, "active": False}, message=_("Product already archived."))
        product.write({"active": False})
        _logger.info("Product archived: id=%s, name=%s", product.id, product.name)
        return self._success({"id": product.id, "active": False}, message=_("Product archived."))
    
    @http.route("/api/v1/products/search", auth="public", methods=["POST", "GET"], type="http", csrf=False)
    def search_products(self, **kwargs):
        """POST /api/v1/products/search - Search products."""
        return self._handle_route(lambda env: self._search_products(env))
    
    def _search_products(self, env):
        data = self._parse_json_data() if request.httprequest.method == "POST" else request.params
        query = data.get("query", "")
        limit = min(int(data.get("limit", 50)), 200)
        
        domain = [("active", "=", True)]
        if query:
            domain += [
                "|", "|", "|",
                ("name", "ilike", query),
                ("default_code", "ilike", query),
                ("barcode", "ilike", query),
                ("description", "ilike", query),
            ]
        if data.get("category_id"):
            domain.append(("categ_id", "=", int(data["category_id"])))
        if data.get("min_price"):
            domain.append(("list_price", ">=", float(data["min_price"])))
        if data.get("max_price"):
            domain.append(("list_price", "<=", float(data["max_price"])))
        
        products = env["product.template"].search(domain, limit=limit)
        return self._success({
            "items": [self._serialize_product(p) for p in products],
            "total": len(products),
        })
