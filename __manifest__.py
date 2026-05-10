{
    "name": "Havano Odoo API",
    "version": "19.0.2.0.0",
    "category": "Sales",
    "summary": "Production-ready REST API for Havano POS with native Odoo authentication",
    "description": """
Havano POS Integration API - Production Ready
=============================================

Native Odoo session-based REST API for seamless POS synchronization.

**Features:**
- Simple username/password authentication (no token management)
- Products CRUD with intelligent SKU matching
- Customer management with email/phone deduplication
- Sales orders with automatic tax resolution
- Invoice creation and posting
- Credit notes with reversal support
- Payment tracking and overdue management
- Real-time stock queries
- Dashboard analytics endpoints
- Comprehensive error handling
- Detailed logging for debugging

**Authentication:**
Just use normal Odoo credentials - session is maintained automatically!
    """,
    "author": "Havano",
    "website": "https://www.havano.com",
    "license": "LGPL-3",
    "depends": [
        "base",
        "product",
        "sale_management",
        "account",
        "stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/api_docs_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}