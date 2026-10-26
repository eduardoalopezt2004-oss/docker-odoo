{
    "name": "Préstamo de equipos",
    "summary": "Registra quién se lleva cada equipo de Mantenimiento y cuándo lo devuelve",
    "version": "18.0.1.0.0",
    "category": "Manufacturing/Maintenance",
    "author": "Binaural",
    "license": "LGPL-3",
    "depends": ["maintenance"],
    "data": [
        "security/ir.model.access.csv",
        "security/maintenance_equipment_loan_security.xml",
        "views/equipment_loan_views.xml",
    ],
    "installable": True,
}
