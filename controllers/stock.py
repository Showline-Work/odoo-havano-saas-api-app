from odoo import http, fields, _  
from odoo.http import request
from odoo.exceptions import ValidationError
from .common import HavanoApiControllerMixin

import logging
_logger = logging.getLogger(__name__)

class HavanoStockController(HavanoApiControllerMixin, http.Controller):
    
    # =========================================================================
    # WAREHOUSE ENDPOINTS
    # =========================================================================
    
    @http.route("/api/v1/stock/warehouses", auth="public", methods=["GET"], type="http", csrf=False)
    def get_warehouses(self, **kwargs):
        """GET /api/v1/stock/warehouses - List all warehouses with basic info"""
        return self._handle_route(lambda env: self._get_warehouses(env))
    
    def _get_warehouses(self, env):
        warehouses = env["stock.warehouse"].search_read(
            domain=[],
            fields=["id", "name", "code", "company_id", "partner_id", "active"],
            order="id",
        )
        
        for wh in warehouses:
            warehouse = env["stock.warehouse"].browse(wh["id"])
            wh["location_id"] = warehouse.lot_stock_id.id
            wh["location_name"] = warehouse.lot_stock_id.name
            wh["in_type_id"] = warehouse.in_type_id.id
            wh["out_type_id"] = warehouse.out_type_id.id
        
        return self._success({
            "items": warehouses,
            "total": len(warehouses),
        })
    
    # =========================================================================
    # STOCK LEVELS ENDPOINTS
    # =========================================================================
    
    @http.route("/api/v1/stock/levels", auth="public", methods=["GET", "POST"], type="http", csrf=False)
    def get_stock_levels(self, limit=100, offset=0, warehouse_id=None, **kwargs):
        """GET /api/v1/stock/levels?warehouse_id=1"""
        return self._handle_route(lambda env: self._get_stock(env, limit, offset, warehouse_id))
    
    def _get_stock(self, env, limit, offset, warehouse_id):
        try:
            limit = min(int(limit), 500)
            offset = int(offset) if offset else 0
        except (ValueError, TypeError):
            limit, offset = 100, 0
        
        Product = env["product.product"]
        # NO type filter - get ALL active products
        products = Product.search(
            [("active", "=", True)],
            limit=limit, offset=offset, order="id desc"
        )
        
        if warehouse_id:
            warehouse = env["stock.warehouse"].browse(int(warehouse_id))
            if not warehouse.exists():
                raise ValidationError(_("Warehouse #%s not found.") % warehouse_id)
            
            items = [self._get_warehouse_stock(env, p, warehouse) for p in products]
            return self._success({
                "items": items,
                "total": len(items),
                "warehouse_id": warehouse.id,
                "warehouse_name": warehouse.name,
            })
        
        items = [self._get_general_stock(env, p) for p in products]
        return self._success({
            "items": items,
            "total": len(items),
        })
    
    def _get_warehouse_locations(self, env, warehouse):
        """Get ALL locations in a warehouse using child_of"""
        return env["stock.location"].search([
            ("id", "child_of", warehouse.view_location_id.id),
        ])
    
    def _get_warehouse_stock(self, env, product, warehouse):
        """Get stock quantities for a product in a specific warehouse"""
        all_locs = self._get_warehouse_locations(env, warehouse)
        
        quants = env["stock.quant"].search([
            ("product_id", "=", product.id),
            ("location_id", "in", all_locs.ids),
        ])
        
        total_qty = sum(quants.mapped("quantity"))
        reserved_qty = sum(quants.mapped("reserved_quantity"))
        
        if total_qty > 0:
            _logger.debug("Product %s: qty=%s in warehouse %s", 
                         product.name, total_qty, warehouse.name)
        
        return {
            "id": product.id,
            "name": product.name or "",
            "display_name": product.display_name or "",
            "default_code": product.default_code or "",
            "barcode": product.barcode or "",
            "qty_available": total_qty,
            "reserved_quantity": reserved_qty,
            "available_quantity": total_qty - reserved_qty,
            "virtual_available": product.virtual_available,
            "incoming_qty": product.incoming_qty if hasattr(product, 'incoming_qty') else 0,
            "outgoing_qty": product.outgoing_qty if hasattr(product, 'outgoing_qty') else 0,
            "uom_id": product.uom_id.id,
            "uom_name": product.uom_name or "",
            "list_price": product.list_price,
            "standard_price": product.standard_price,
            "warehouse_id": warehouse.id,
            "warehouse_name": warehouse.name,
            "warehouse_code": warehouse.code,
            "categ_id": product.categ_id.id,
            "categ_name": product.categ_id.name or "",
            "type": product.type or "product",
            "active": product.active,
            "image_128": product.image_128.decode() if product.image_128 else None,
        }
    
    def _get_general_stock(self, env, product):
        """Get general stock quantities (all warehouses)"""
        return {
            "id": product.id,
            "name": product.name or "",
            "display_name": product.display_name or "",
            "default_code": product.default_code or "",
            "barcode": product.barcode or "",
            "qty_available": product.qty_available,
            "virtual_available": product.virtual_available,
            "incoming_qty": product.incoming_qty if hasattr(product, 'incoming_qty') else 0,
            "outgoing_qty": product.outgoing_qty if hasattr(product, 'outgoing_qty') else 0,
            "uom_id": product.uom_id.id,
            "uom_name": product.uom_name or "",
            "list_price": product.list_price,
            "standard_price": product.standard_price,
            "categ_id": product.categ_id.id,
            "categ_name": product.categ_id.name or "",
            "type": product.type or "product",
            "active": product.active,
            "image_128": product.image_128.decode() if product.image_128 else None,
        }
    
    @http.route("/api/v1/stock/warehouse/<int:warehouse_id>/products", auth="public", methods=["GET", "POST"], type="http", csrf=False)
    def get_warehouse_products(self, warehouse_id, limit=100, offset=0, **kwargs):
        """GET /api/v1/stock/warehouse/1/products"""
        return self._handle_route(lambda env: self._get_warehouse_products(env, warehouse_id, limit, offset))
    
    def _get_warehouse_products(self, env, warehouse_id, limit, offset):
        try:
            limit = min(int(limit), 500)
            offset = int(offset) if offset else 0
        except (ValueError, TypeError):
            limit, offset = 100, 0
        
        warehouse = env["stock.warehouse"].browse(warehouse_id)
        if not warehouse.exists():
            raise ValidationError(_("Warehouse #%s not found.") % warehouse_id)
        
        Product = env["product.product"]
        # NO type filter - get ALL active products
        products = Product.search(
            [("active", "=", True)],
            limit=limit, offset=offset, order="id desc"
        )
        
        items = [self._get_warehouse_stock(env, p, warehouse) for p in products]
        
        return self._success({
            "items": items,
            "total": len(items),
            "warehouse": {
                "id": warehouse.id,
                "name": warehouse.name,
                "code": warehouse.code,
            },
            "limit": limit,
            "offset": offset,
        })
    
    @http.route("/api/v1/stock/product/<int:product_id>/warehouses", auth="public", methods=["GET"], type="http", csrf=False)
    def get_product_warehouse_stock(self, product_id, **kwargs):
        """GET /api/v1/stock/product/45/warehouses"""
        return self._handle_route(lambda env: self._get_product_warehouses(env, product_id))
    
    def _get_product_warehouses(self, env, product_id):
        product = env["product.product"].browse(product_id)
        if not product.exists():
            raise ValidationError(_("Product #%s not found.") % product_id)
        
        warehouses = env["stock.warehouse"].search([])
        warehouse_stock = []
        
        for wh in warehouses:
            all_locs = self._get_warehouse_locations(env, wh)
            
            quants = env["stock.quant"].search([
                ("product_id", "=", product.id),
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
        
        return self._success({
            "product_id": product.id,
            "product_name": product.name,
            "default_code": product.default_code or "",
            "warehouses": warehouse_stock,
        })
    
    # =========================================================================
    # STOCK TRANSFER / SYNC ENDPOINTS
    # =========================================================================
    
    @http.route("/api/v1/stock/transfer", auth="public", methods=["POST"], type="http", csrf=False)
    def create_stock_transfer(self, **kwargs):
        """POST /api/v1/stock/transfer"""
        return self._handle_route(lambda env: self._create_transfer(env))
    
    def _create_transfer(self, env):
        data = self._parse_json_data()
        
        warehouse_id = data.get("warehouse_id")
        lines = data.get("lines", [])
        reference = data.get("reference", "")
        partner_id = data.get("partner_id")
        
        if not warehouse_id:
            raise ValidationError(_("warehouse_id is required."))
        if not lines:
            raise ValidationError(_("At least one line is required."))
        
        warehouse = env["stock.warehouse"].browse(int(warehouse_id))
        if not warehouse.exists():
            raise ValidationError(_("Warehouse #%s not found.") % warehouse_id)
        
        picking_type = warehouse.out_type_id
        
        move_lines = []
        for line_data in lines:
            product_id = line_data.get("product_id")
            quantity = float(line_data.get("quantity", 1))
            
            if not product_id:
                continue
            
            product = env["product.product"].browse(int(product_id))
            if not product.exists():
                continue
            
            move_lines.append((0, 0, {
                "product_id": product.id,
                "name": product.display_name,
                "product_uom_qty": quantity,
                "product_uom": product.uom_id.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
                "quantity": quantity,
            }))
        
        if not move_lines:
            raise ValidationError(_("No valid products found."))
        
        picking_vals = {
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "move_ids": move_lines,
            "origin": reference,
        }
        
        if partner_id:
            partner = env["res.partner"].browse(int(partner_id))
            if partner.exists():
                picking_vals["partner_id"] = partner.id
        
        picking = env["stock.picking"].create(picking_vals)
        
        _logger.info("Stock transfer created: %s (warehouse=%s, lines=%s)",
                    picking.name, warehouse.name, len(move_lines))
        
        return self._success({
            "picking_id": picking.id,
            "picking_name": picking.name,
            "state": picking.state,
            "warehouse_id": warehouse.id,
            "warehouse_name": warehouse.name,
            "lines_count": len(move_lines),
        }, message=_("Stock transfer created."), status=201)
    
    @http.route("/api/v1/stock/transfer/<int:picking_id>/validate", auth="public", methods=["POST"], type="http", csrf=False)
    def validate_transfer(self, picking_id, **kwargs):
        """POST /api/v1/stock/transfer/:id/validate"""
        return self._handle_route(lambda env: self._validate_transfer(env, picking_id))
    
    def _validate_transfer(self, env, picking_id):
        picking = env["stock.picking"].browse(picking_id)
        if not picking.exists():
            raise ValidationError(_("Transfer #%s not found.") % picking_id)
        
        if picking.state == "done":
            return self._success({
                "picking_id": picking.id,
                "state": picking.state,
            }, message=_("Transfer already validated."))
        
        picking.action_confirm()
        picking.action_assign()
        picking.button_validate()
        
        return self._success({
            "picking_id": picking.id,
            "picking_name": picking.name,
            "state": picking.state,
        }, message=_("Transfer validated."))
    
    @http.route("/api/v1/stock/sync", auth="public", methods=["POST"], type="http", csrf=False)
    def sync_stock_from_pos(self, **kwargs):
        """POST /api/v1/stock/sync"""
        return self._handle_route(lambda env: self._sync_stock(env))
    
    def _sync_stock(self, env):
        data = self._parse_json_data()
        warehouse_id = data.get("warehouse_id")
        updates = data.get("updates", [])
        reference = data.get("reference", "POS Sync")
        partner_id = data.get("partner_id")
        
        if not warehouse_id:
            raise ValidationError(_("warehouse_id is required."))
        if not updates:
            raise ValidationError(_("updates array is required."))
        
        warehouse = env["stock.warehouse"].browse(int(warehouse_id))
        if not warehouse.exists():
            raise ValidationError(_("Warehouse #%s not found.") % warehouse_id)
        
        picking_type = warehouse.out_type_id
        
        move_lines = []
        synced_products = []
        
        for update in updates:
            product_id = update.get("product_id")
            quantity = float(update.get("quantity_sold", 1))
            
            if not product_id:
                continue
            
            product = env["product.product"].browse(int(product_id))
            if not product.exists():
                continue
            
            move_lines.append((0, 0, {
                "product_id": product.id,
                "name": product.display_name,
                "product_uom_qty": quantity,
                "product_uom": product.uom_id.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
                "quantity": quantity,
            }))
            
            synced_products.append({
                "product_id": product.id,
                "product_name": product.name,
                "quantity": quantity,
            })
        
        if not move_lines:
            raise ValidationError(_("No valid products to sync."))
        
        picking_vals = {
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "move_ids": move_lines,
            "origin": reference,
        }
        
        if partner_id:
            partner = env["res.partner"].browse(int(partner_id))
            if partner.exists():
                picking_vals["partner_id"] = partner.id
        
        picking = env["stock.picking"].create(picking_vals)
        picking.action_confirm()
        picking.action_assign()
        
        try:
            picking.button_validate()
        except Exception as e:
            _logger.warning("Could not auto-validate picking %s: %s", picking.name, str(e))
        
        return self._success({
            "picking_id": picking.id,
            "picking_name": picking.name,
            "state": picking.state,
            "warehouse_id": warehouse.id,
            "warehouse_name": warehouse.name,
            "products": synced_products,
        }, message=_("Stock synced successfully."), status=201)
    
    @http.route("/api/v1/stock/low", auth="public", methods=["GET", "POST"], type="http", csrf=False)
    def get_low_stock(self, threshold=10, warehouse_id=None, **kwargs):
        """GET /api/v1/stock/low?threshold=10&warehouse_id=1"""
        return self._handle_route(lambda env: self._get_low_stock(env, threshold, warehouse_id))
    
    def _get_low_stock(self, env, threshold, warehouse_id):
        try:
            threshold = float(threshold)
        except (ValueError, TypeError):
            threshold = 10
        
        Product = env["product.product"]
        products = Product.search(
            [("active", "=", True)],
            order="id desc", limit=500
        )
        
        if warehouse_id:
            warehouse = env["stock.warehouse"].browse(int(warehouse_id))
            if warehouse.exists():
                items = []
                for p in products:
                    stock = self._get_warehouse_stock(env, p, warehouse)
                    if stock["available_quantity"] < threshold:
                        items.append(stock)
                items = sorted(items, key=lambda x: x["available_quantity"])[:100]
            else:
                items = []
        else:
            items = []
            for p in products:
                if p.qty_available < threshold:
                    items.append(self._get_general_stock(env, p))
            items = sorted(items, key=lambda x: x["qty_available"])[:100]
        
        return self._success({
            "items": items,
            "total": len(items),
            "threshold": threshold,
        })