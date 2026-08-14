import frappe


def after_install():
	"""Ensure the Super PDP Settings single document exists with sane
	defaults right after the app is installed, so the settings page never
	shows an empty/uninitialised doctype."""
	if not frappe.db.exists("Singles", {"doctype": "Super PDP Settings"}):
		doc = frappe.new_doc("Super PDP Settings")
		doc.superpdp_endpoint = "https://api.superpdp.tech"
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
