# -*- coding: utf-8 -*-
"""
Creates the default "Super PDP XML Template" (from the SuperPDP sample
XML) and its "Super PDP XML Field Mapping" rows (from
xml_mapping_defaults.DEFAULT_MAPPING_ROWS) if they don't already exist.
Safe to call repeatedly - it never overwrites rows an admin has since
edited; use reset_default_mapping() explicitly to discard local edits
and reseed from the shipped defaults.
"""

import frappe

from pdp_integration.xml_sample import SAMPLE_INVOICE_XML
from pdp_integration.xml_mapping_defaults import DEFAULT_TEMPLATE_NAME, DEFAULT_MAPPING_ROWS


def ensure_default_template():
	if frappe.db.exists("Super PDP XML Template", DEFAULT_TEMPLATE_NAME):
		return DEFAULT_TEMPLATE_NAME

	doc = frappe.new_doc("Super PDP XML Template")
	doc.template_name = DEFAULT_TEMPLATE_NAME
	doc.is_default = 1
	doc.description = (
		"UBL 2.1 / EN16931 invoice, seeded from the SuperPDP sandbox sample "
		"(test_invoice.xml). Structural reference only - no real customer data."
	)
	doc.raw_xml = SAMPLE_INVOICE_XML
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_default_mapping(template_name=None):
	template_name = template_name or ensure_default_template()

	existing = frappe.db.exists("Super PDP XML Field Mapping", {"template": template_name})
	if existing:
		return

	for row in DEFAULT_MAPPING_ROWS:
		doc = frappe.new_doc("Super PDP XML Field Mapping")
		doc.template = template_name
		doc.update(row)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()


def seed_all():
	template_name = ensure_default_template()
	ensure_default_mapping(template_name)
	return template_name


@frappe.whitelist()
def get_seed_status():
	"""Tells the UI whether default config exists yet, so it can offer to
	create it on the spot for sites where the app was installed before
	this feature existed (after_install only runs on a fresh install -
	after_migrate and this on-demand call cover upgrades too)."""
	template_name = frappe.db.get_value("Super PDP XML Template", {"is_default": 1}, "name")
	mapping_count = 0
	if template_name:
		mapping_count = frappe.db.count("Super PDP XML Field Mapping", {"template": template_name})
	return {
		"template": template_name,
		"mapping_count": mapping_count,
		"is_seeded": bool(template_name and mapping_count),
		"expected_rows": len(DEFAULT_MAPPING_ROWS),
	}


@frappe.whitelist()
def seed_defaults():
	"""Idempotent: creates the default template/mapping if missing, does
	nothing (keeps admin edits) if they already exist. Safe to call from
	the UI at any time - unlike reset_default_mapping(), this never
	deletes anything."""
	frappe.only_for("System Manager")
	template_name = seed_all()
	status = get_seed_status()
	status["template"] = template_name
	return status


@frappe.whitelist()
def reset_default_mapping():
	"""Deletes all mapping rows for the default template and reseeds them
	from xml_mapping_defaults.DEFAULT_MAPPING_ROWS, discarding any local
	edits. System Manager only - this is a deliberate, explicit action."""
	frappe.only_for("System Manager")

	template_name = ensure_default_template()
	frappe.db.delete("Super PDP XML Field Mapping", {"template": template_name})
	ensure_default_mapping(template_name)
	frappe.db.commit()
	return {"template": template_name, "rows": len(DEFAULT_MAPPING_ROWS)}
