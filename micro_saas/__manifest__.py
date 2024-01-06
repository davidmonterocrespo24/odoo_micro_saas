{
    "name": "Odoo Docker Instance Management",
    "category": "Tools",
    "summary": "Manage Odoo instances using Docker Compose",
    "description": """
        This module allows you to manage Odoo instances using Docker Compose.
    """,
    "author": "David Montero Crespo",
    "website": "https://github.com/davidmonterocrespo24/odoo_micro_saas",
    "license": "AGPL-3",
    "version": "17.0.1.2",
    "depends": ["base"],
    "data": [
        "views/menu.xml",
        "security/ir.model.access.csv",
        "views/odoo_docker_instance.xml",
        "views/repository_repo.xml",
        "views/docker_compose_template.xml",
        "data/data.xml",
    ],
    "images": ["static/icon.png"],
    "demo": [],
    "installable": True,
    "application": True,
    "auto_install": False,

}
