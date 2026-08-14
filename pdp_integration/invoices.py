# -*- coding: utf-8 -*-
"""
Bridges ERPNext invoices (Sales Invoice / Purchase Invoice) to the ported
SuperPDP functions.

Role detection is simple and explicit:
  - Sales Invoice  -> ERPNext company is the SELLER  -> seller-role functions
  - Purchase Invoice -> ERPNext company is the BUYER -> buyer-role functions

"Test with SuperPDP" runs the relevant SuperPDP *sandbox* pipeline for
that role (the SuperPDP functions in the ZIP are sandbox/test endpoints
built around a generated test invoice, not a UBL exporter for arbitrary
invoice data) and logs every step against the ERPNext invoice, so the
result is fully auditable from the invoice's SuperPDP log.
"""

import frappe
from frappe import _
from frappe.utils import flt

from pdp_integration.superpdp_functions import (
	run_seller_token,
	run_seller_company,
	run_generate_invoice,
	run_validate_invoice,
	run_buyer_token,
	run_list_buyer_invoices,
	run_send_invoice,
)

INVOICE_DOCTYPES = ("Sales Invoice", "Purchase Invoice")


def _role_for_doctype(invoice_doctype):
	if invoice_doctype == "Sales Invoice":
		return "Seller"
	if invoice_doctype == "Purchase Invoice":
		return "Buyer"
	frappe.throw(f"Unsupported invoice doctype for SuperPDP: {invoice_doctype}")


@frappe.whitelist()
def get_invoices(invoice_doctype="Sales Invoice", limit=50, search=None):
	if invoice_doctype not in INVOICE_DOCTYPES:
		frappe.throw("invoice_doctype must be 'Sales Invoice' or 'Purchase Invoice'")

	limit = min(int(limit or 50), 200)
	party_field = "customer" if invoice_doctype == "Sales Invoice" else "supplier"
	party_name_field = "customer_name" if invoice_doctype == "Sales Invoice" else "supplier_name"

	filters = {"docstatus": ["!=", 2]}
	or_filters = None
	if search:
		or_filters = {
			"name": ["like", f"%{search}%"],
			party_field: ["like", f"%{search}%"],
		}

	fields = [
		"name",
		party_field,
		party_name_field,
		"posting_date",
		"due_date",
		"grand_total",
		"currency",
		"status",
		"docstatus",
	]

	rows = frappe.get_list(
		invoice_doctype,
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by="posting_date desc, creation desc",
		limit_page_length=limit,
		ignore_permissions=False,
	)

	for row in rows:
		row["party"] = row.get(party_name_field) or row.get(party_field)
		row["role"] = _role_for_doctype(invoice_doctype)

	return {"invoice_doctype": invoice_doctype, "role": _role_for_doctype(invoice_doctype), "invoices": rows}


@frappe.whitelist()
def get_invoice_log(invoice_doctype, invoice):
	return frappe.get_list(
		"Super PDP Invoice Log",
		filters={"invoice_doctype": invoice_doctype, "invoice": invoice},
		fields=[
			"name",
			"function_id",
			"function_label",
			"status",
			"http_status",
			"error",
			"executed_by",
			"executed_on",
		],
		order_by="executed_on desc",
		limit_page_length=50,
	)


@frappe.whitelist()
def test_invoice_with_superpdp(invoice_doctype, invoice_name):
	"""Detects the invoice's role (seller for Sales Invoice, buyer for
	Purchase Invoice) and runs the matching SuperPDP sandbox pipeline,
	logging every step against this specific ERPNext invoice."""

	if invoice_doctype not in INVOICE_DOCTYPES:
		frappe.throw("invoice_doctype must be 'Sales Invoice' or 'Purchase Invoice'")

	if not frappe.db.exists(invoice_doctype, invoice_name):
		frappe.throw(f"{invoice_doctype} {invoice_name} not found")

	frappe.has_permission(invoice_doctype, doc=invoice_name, throw=True)

	role = _role_for_doctype(invoice_doctype)
	steps = []

	if role == "Seller":
		steps.append(_wrap_step(run_seller_token, invoice_doctype, invoice_name))
		if steps[-1]["ok"]:
			steps.append(_wrap_step(run_seller_company, invoice_doctype, invoice_name))
		if steps and steps[-1]["ok"]:
			steps.append(_wrap_step(run_generate_invoice, invoice_doctype, invoice_name))
		if steps and steps[-1]["ok"]:
			steps.append(_wrap_step(run_validate_invoice, invoice_doctype, invoice_name))

		invoice_doc = frappe.get_cached_doc(invoice_doctype, invoice_name)
		summary = _build_summary(steps, extra={
			"erpnext_invoice_amount": flt(invoice_doc.grand_total),
			"erpnext_invoice_currency": invoice_doc.currency,
			"note": (
				"Seller-role SuperPDP sandbox pipeline: OAuth token, company lookup, "
				"generate + validate a test invoice. This exercises SuperPDP "
				"connectivity/flow for this invoice's role; it validates a SuperPDP "
				"sandbox test invoice rather than a UBL export of this exact ERPNext invoice."
			),
		})
	else:
		steps.append(_wrap_step(run_buyer_token, invoice_doctype, invoice_name))
		if steps[-1]["ok"]:
			steps.append(_wrap_step(run_list_buyer_invoices, invoice_doctype, invoice_name))

		invoice_doc = frappe.get_cached_doc(invoice_doctype, invoice_name)
		matched = None
		if steps and steps[-1]["ok"]:
			candidates = ((steps[-1].get("response") or {}).get("invoices") or [])
			for candidate in candidates:
				if str(candidate.get("number")) == invoice_doc.name:
					matched = candidate
					break

		summary = _build_summary(steps, extra={
			"erpnext_invoice_amount": flt(invoice_doc.grand_total),
			"erpnext_invoice_currency": invoice_doc.currency,
			"heuristic_match": matched,
			"note": (
				"Buyer-role SuperPDP sandbox pipeline: OAuth token, list invoices "
				"visible to the buyer. 'heuristic_match' is a best-effort match by "
				"invoice number against the SuperPDP buyer inbox, not an authoritative link."
			),
		})

	return {"role": role, "steps": steps, "summary": summary}


@frappe.whitelist()
def send_invoice_to_superpdp(invoice_doctype, invoice_name):
	"""Runs SuperPDP function 07 (Send Invoice) for a Sales Invoice: the
	seller role generates a fresh sandbox test invoice (function 04) and
	sends it (POST /v1.beta/invoices), logging both steps against this
	ERPNext invoice. Only meaningful for the seller side (Sales Invoice) -
	a Purchase Invoice is something we *receive*, not something we send."""

	if invoice_doctype != "Sales Invoice":
		frappe.throw(_("Sending to SuperPDP is only available for Sales Invoices (seller role)."))

	if not frappe.db.exists(invoice_doctype, invoice_name):
		frappe.throw(f"{invoice_doctype} {invoice_name} not found")

	frappe.has_permission(invoice_doctype, doc=invoice_name, throw=True)

	steps = []
	steps.append(_wrap_step(run_generate_invoice, invoice_doctype, invoice_name))
	if steps[-1]["ok"]:
		steps.append(_wrap_step(run_send_invoice, invoice_doctype, invoice_name))

	invoice_doc = frappe.get_cached_doc(invoice_doctype, invoice_name)

	superpdp_invoice_id = None
	send_step = next((s for s in steps if s["function_id"] == "07_send_invoice"), None)
	if send_step and send_step["ok"] and isinstance(send_step.get("response"), dict):
		superpdp_invoice_id = send_step["response"].get("id")

	summary = _build_summary(
		steps,
		extra={
			"erpnext_invoice_amount": flt(invoice_doc.grand_total),
			"erpnext_invoice_currency": invoice_doc.currency,
			"superpdp_invoice_id": superpdp_invoice_id,
			"note": (
				"Generates a fresh SuperPDP sandbox test invoice and sends it "
				"(POST /v1.beta/invoices) as the seller. This exercises the real "
				"'send' call against the SuperPDP sandbox test invoice, not a "
				"UBL export of this exact ERPNext invoice's line items."
			),
		},
	)

	return {"role": "Seller", "steps": steps, "summary": summary}


def _wrap_step(fn, invoice_doctype, invoice_name):
	result = fn(invoice_doctype=invoice_doctype, invoice=invoice_name)
	meta = _meta_for(fn)
	return {
		"function_id": meta["id"],
		"label": meta["label"],
		"ok": result.get("ok"),
		"http_status": result.get("http_status"),
		"response": result.get("response"),
		"error": result.get("error"),
	}


def _meta_for(fn):
	from pdp_integration.superpdp_functions import FUNCTION_REGISTRY

	name = fn.__name__
	for item in FUNCTION_REGISTRY:
		if item["method"].endswith(name):
			return item
	return {"id": name, "label": name}


def _build_summary(steps, extra=None):
	all_ok = all(step["ok"] for step in steps) if steps else False
	summary = {"overall": "Success" if all_ok else "Failed", "steps_run": len(steps)}
	if extra:
		summary.update(extra)
	return summary
