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

	# Seed the default "Super PDP XML Template" + its "Super PDP XML Field
	# Mapping" rows so the XML Configuration page has something to show
	# (and "Send to SuperPDP" has a mapping to resolve against) right after
	# install, without requiring a manual setup step.
	from pdp_integration.xml_seed import seed_all

	seed_all()

	# The "PDP Integration" Workspace ships as a standard doc under
	# pdp_integration/pdp_integration/workspace/ and is synced into the
	# Workspace doctype automatically during install/migrate. Clear the
	# desk cache so the sidebar picks it up immediately without requiring
	# a manual "Reload" from the user.
	frappe.clear_cache()
