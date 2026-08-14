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

	# The "PDP Integration" Workspace ships as a standard doc under
	# pdp_integration/pdp_integration/workspace/ and is synced into the
	# Workspace doctype automatically during install/migrate. Clear the
	# desk cache so the sidebar picks it up immediately without requiring
	# a manual "Reload" from the user.
	frappe.clear_cache()
