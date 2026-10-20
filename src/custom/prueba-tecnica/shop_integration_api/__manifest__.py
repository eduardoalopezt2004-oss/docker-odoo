{
    "name": "API de productos y pedidos para la tienda en línea",
    "summary": "Catálogo de productos y pedidos en JSON para la tienda en línea del cliente",
    "version": "18.0.1.2.0",
    "category": "Sales",
    "author": "Binaural",
    "license": "LGPL-3",
    "depends": ["base_setup", "sale", "stock", "sale_stock"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/shop_api_log_views.xml",
        "views/shop_webhook_event_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
}
