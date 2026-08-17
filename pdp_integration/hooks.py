app_name = "pdp_integration"
app_title = "PDP Integration"
app_publisher = "Your Organization"
app_description = (
    "SuperPDP (French e-invoicing PDP / Plateforme de Dematerialisation "
    "Partenaire) integration for ERPNext: configure SuperPDP credentials, "
    "browse Sales/Purchase Invoices and test them against SuperPDP, and "
    "run every SuperPDP sandbox function individually from the Desk."
)
app_email = "dev@example.com"
app_license = "MIT"
app_icon = "octicon octicon-plug"
app_color = "#2e7d32"

# This app is a companion to an existing ERPNext installation - it reuses
# ERPNext's Sales Invoice / Purchase Invoice doctypes.
required_apps = ["erpnext"]

# Includes in <head>
# ------------------
app_include_css = "/assets/pdp_integration/css/pdp_integration.css"

# Installation
# ------------
after_install = "pdp_integration.setup.install.after_install"
after_migrate = "pdp_integration.setup.install.after_migrate"

# Fixtures
# --------
# (none - all configuration lives in the "Super PDP Settings" single doctype,
# credentials are stored via Frappe's encrypted Password fieldtype)
