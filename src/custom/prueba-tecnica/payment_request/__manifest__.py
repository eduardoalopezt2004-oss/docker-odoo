{
    "name": "Solicitudes de pago",
    "summary": "Solicitudes de pago a proveedores con flujo de aprobación",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "author": "Binaural",
    "license": "LGPL-3",
    "depends": ["mail"],
    "data": [
        "security/payment_request_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
    ],
    "installable": True,
    "application": True,
}
