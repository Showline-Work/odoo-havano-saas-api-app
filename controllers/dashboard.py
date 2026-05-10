from odoo import http
from odoo.http import request
from .common import HavanoApiControllerMixin

class HavanoDashboardController(HavanoApiControllerMixin, http.Controller):
    
    @http.route("/api/v1/dashboard", auth="public", methods=["GET", "POST"], type="json", csrf=False)
    def get_dashboard(self, **kwargs):
        """GET /api/v1/dashboard - Get dashboard summary."""
        return self._handle_route(lambda env: self._get_dashboard(env))
    
    def _get_dashboard(self, env):
        SaleOrder = env["sale.order"]
        Invoice = env["account.move"]
        Product = env["product.template"]
        Partner = env["res.partner"]
        
        # Today's stats
        from datetime import date, timedelta
        today = date.today()
        this_month_start = today.replace(day=1)
        
        # Sales stats
        total_orders = SaleOrder.search_count([])
        confirmed_orders = SaleOrder.search_count([("state", "in", ["sale", "done"])])
        draft_quotations = SaleOrder.search_count([("state", "=", "draft")])
        
        # Today's sales
        today_orders = SaleOrder.search_count([
            ("date_order", ">=", str(today)),
            ("state", "in", ["sale", "done"]),
        ])
        
        # Monthly revenue
        monthly_orders = SaleOrder.search([
            ("date_order", ">=", str(this_month_start)),
            ("state", "in", ["sale", "done"]),
        ])
        monthly_revenue = sum(o.amount_total for o in monthly_orders)
        
        # Invoice stats
        total_invoices = Invoice.search_count([("move_type", "=", "out_invoice")])
        posted_invoices = Invoice.search_count([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
        ])
        
        # Overdue
        overdue = Invoice.search_count([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "!=", "paid"),
            ("invoice_date_due", "<", str(today)),
        ])
        
        # Product & Customer counts
        total_products = Product.search_count([("active", "=", True)])
        total_customers = Partner.search_count([("customer_rank", ">", 0)])
        
        return self._success({
            "orders": {
                "total": total_orders,
                "confirmed": confirmed_orders,
                "draft_quotations": draft_quotations,
                "today": today_orders,
            },
            "revenue": {
                "this_month": monthly_revenue,
            },
            "invoices": {
                "total": total_invoices,
                "posted": posted_invoices,
                "overdue": overdue,
            },
            "catalog": {
                "products": total_products,
                "customers": total_customers,
            },
        })
    
    @http.route("/api/v1/dashboard/top-products", auth="public", methods=["GET", "POST"], type="json", csrf=False)
    def get_top_products(self, limit=10, **kwargs):
        """GET /api/v1/dashboard/top-products - Get top selling products."""
        return self._handle_route(lambda env: self._get_top_products(env, limit))
    
    def _get_top_products(self, env, limit):
        try:
            limit = min(int(limit), 50)
        except (ValueError, TypeError):
            limit = 10
        
        # Group by product and sum quantities
        result = env["sale.order.line"].read_group(
            domain=[("state", "in", ["sale", "done"])],
            fields=["product_id", "product_uom_qty:sum", "price_subtotal:sum"],
            groupby=["product_id"],
            orderby="product_uom_qty desc",
            limit=limit,
        )
        
        return self._success({
            "items": result,
            "limit": limit,
        })