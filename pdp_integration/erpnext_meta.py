# -*- coding: utf-8 -*-
"""
Read-only discovery of real ERPNext metadata (doctypes, fields, records)
for the "Super PDP XML Configuration" page and the mapping editor. This
module never hardcodes field lists or company/customer data - it always
asks the installed ERPNext instance, which stays the single source of
truth.
"""

import frappe

_SKIP_FIELDTYPES = {
	"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading",
}

# Doctypes an admin is realistically mapping XML fields from/to. Kept as a
# curated list (not "all doctypes") purely to make the picker usable -
# any doctype can still be typed directly into erpnext_doctype since it's
# a normal Link field, this just powers a convenient default list.
MAPPABLE_DOCTYPES = [
	{"doctype": "Sales Invoice", "label": "Sales Invoice (header)"},
	{"doctype": "Sales Invoice Item", "label": "Sales Invoice Item (line)"},
	{"doctype": "Company", "label": "Company (seller)"},
	{"doctype": "Customer", "label": "Customer (buyer)"},
	{"doctype": "Super PDP Settings", "label": "Super PDP Settings (SIRET, endpoint)"},
]


@frappe.whitelist()
def get_mappable_doctypes():
	return MAPPABLE_DOCTYPES


@frappe.whitelist()
def get_doctype_fields(doctype):
	frappe.has_permission(doctype, throw=True)
	meta = frappe.get_meta(doctype)
	fields = []
	for df in meta.fields:
		if df.fieldtype in _SKIP_FIELDTYPES:
			continue
		fields.append(
			{
				"fieldname": df.fieldname,
				"label": df.label,
				"fieldtype": df.fieldtype,
				"options": df.options,
				"reqd": df.reqd,
			}
		)
	for fieldname, label, fieldtype in (
		("name", "ID / Name", "Data"),
		("owner", "Owner", "Data"),
		("creation", "Created On", "Datetime"),
		("modified", "Last Modified", "Datetime"),
	):
		fields.append({"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "options": None, "reqd": 0})
	return fields


@frappe.whitelist()
def get_companies():
	return frappe.get_list("Company", fields=["name", "company_name"], order_by="name", limit_page_length=200)


@frappe.whitelist()
def get_customers(search=None):
	filters = {}
	or_filters = None
	if search:
		or_filters = {"name": ["like", f"%{search}%"], "customer_name": ["like", f"%{search}%"]}
	return frappe.get_list(
		"Customer",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "customer_name"],
		order_by="modified desc",
		limit_page_length=50,
	)


@frappe.whitelist()
def get_sales_invoices(company=None, customer=None, search=None, limit=50):
	filters = {"docstatus": ["!=", 2]}
	if company:
		filters["company"] = company
	if customer:
		filters["customer"] = customer

	or_filters = None
	if search:
		or_filters = {"name": ["like", f"%{search}%"], "customer": ["like", f"%{search}%"]}

	return frappe.get_list(
		"Sales Invoice",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "customer", "customer_name", "posting_date", "grand_total", "currency", "status"],
		order_by="posting_date desc, creation desc",
		limit_page_length=min(int(limit or 50), 200),
	)
