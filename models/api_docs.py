from odoo import _, fields, models


class HavanoApiDocumentation(models.TransientModel):
    _name = "havano.api.documentation"
    _description = "Havano API Documentation"

    title = fields.Char(default="Havano API Reference", readonly=True)
    content = fields.Html(readonly=True)

    def default_get(self, field_list):
        res = super().default_get(field_list)
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        routes = [
            ("GET", "/api/v1/auth/test", "Validate bearer token and return bound user/company."),
            ("GET", "/api/v1/products", "List synced products."),
            ("GET", "/api/v1/products/<id>", "Fetch one product template by Odoo ID."),
            ("POST", "/api/v1/products", "Create or update a product by external ID or SKU."),
            ("PUT", "/api/v1/products/<id>", "Update an existing product template."),
            ("GET", "/api/v1/customers", "List customers."),
            ("POST", "/api/v1/customers", "Create or update a customer by external ID, phone, or email."),
            ("GET", "/api/v1/sales-orders", "List sales orders."),
            ("POST", "/api/v1/sales-orders", "Create or update a retry-safe sales order."),
            ("POST", "/api/v1/sales-orders/<id>/confirm", "Confirm a sales order safely."),
            ("POST", "/api/v1/invoices", "Create or update a retry-safe invoice."),
            ("POST", "/api/v1/invoices/<id>/post", "Post an invoice safely."),
        ]
        rows = "".join(
            "<tr><td><code>%s</code></td><td><code>%s%s</code></td><td>%s</td></tr>"
            % (method, base_url, path, description)
            for method, path, description in routes
        )
        res["content"] = _(
            """
            <div>
                <h2>Authentication</h2>
                <p>All API requests must send <code>Authorization: Bearer &lt;token&gt;</code>.</p>
                <h2>Response Format</h2>
                <p>Success: <code>{"success": true, "data": {}, "message": ""}</code></p>
                <p>Error: <code>{"success": false, "error": "", "code": 400}</code></p>
                <h2>Available Endpoints</h2>
                <table class="table table-sm table-bordered">
                    <thead>
                        <tr><th>Method</th><th>Endpoint</th><th>Purpose</th></tr>
                    </thead>
                    <tbody>%s</tbody>
                </table>
                <h2>Sync Rules</h2>
                <ul>
                    <li>Products match by <code>external_id</code> first, then <code>default_code</code>.</li>
                    <li>Customers match by <code>external_id</code>, then phone or email.</li>
                    <li>Sales orders and invoices are idempotent on <code>external_id + source</code>.</li>
                </ul>
            </div>
            """
        ) % rows
        return res
