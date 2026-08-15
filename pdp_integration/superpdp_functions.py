# -*- coding: utf-8 -*-
"""
Python ports of the 10 numbered SuperPDP test scripts that shipped in the
original ZIP (01_seller_token.js ... 10_send_paid_event.js).

Each ``run_*`` function below mirrors its JS counterpart 1:1: same
endpoint, same HTTP method, same headers/params/body shape, same order of
operations. They are ported to Python (instead of executed as Node.js)
because a Frappe site's backend runs Python - this is the closest
possible thing to "reusing the existing functions" inside ERPNext.

Where the original scripts persisted state between steps using local
files (test_invoice.xml, uploaded_invoice.json), this port uses Frappe's
cache, scoped per user session, so the same "generate -> validate -> send
-> check status -> send paid event" chain works from the Function
Console UI.

Every function returns a plain dict:
    {
        "ok": bool,
        "http_status": int | None,
        "response": <parsed JSON, text, or summary dict>,
        "error": str | None,
    }
and writes a "Super PDP Invoice Log" entry for traceability.
"""

import json

import frappe
import requests
from frappe.utils import now_datetime

from pdp_integration.pdp_client import (
	SuperPDPError,
	do_request,
	get_buyer_token,
	get_endpoint,
	get_seller_token,
	request_token,
	get_seller_credentials,
	get_buyer_credentials,
)

CACHE_TTL = 3600  # 1 hour, same spirit as re-usable local files in the original scripts


# ---------------------------------------------------------------------------
# Function registry - drives the "Test Every Function" console in the UI
# ---------------------------------------------------------------------------

FUNCTION_REGISTRY = [
	{
		"id": "01_seller_token",
		"label": "Seller OAuth Token",
		"file": "01_seller_token.js",
		"role": "Seller",
		"description": "Obtains an OAuth2 client_credentials token for the seller (BurgerQueen).",
		"method": "pdp_integration.superpdp_functions.run_seller_token",
	},
	{
		"id": "02_buyer_token",
		"label": "Buyer OAuth Token",
		"file": "02_buyer_token.js",
		"role": "Buyer",
		"description": "Obtains an OAuth2 client_credentials token for the buyer (Tricatel).",
		"method": "pdp_integration.superpdp_functions.run_buyer_token",
	},
	{
		"id": "03_seller_company",
		"label": "Seller Company Info",
		"file": "03_seller_company.js",
		"role": "Seller",
		"description": "Fetches the company profile (GET /v1.beta/companies/me) for the seller token.",
		"method": "pdp_integration.superpdp_functions.run_seller_company",
	},
	{
		"id": "04_generate_invoice",
		"label": "Generate Test Invoice",
		"file": "04_generate_invoice.js",
		"role": "Seller",
		"description": "Downloads a sandbox UBL test invoice (GET /v1.beta/invoices/generate_test_invoice).",
		"method": "pdp_integration.superpdp_functions.run_generate_invoice",
	},
	{
		"id": "05_validate_invoice",
		"label": "Validate Invoice",
		"file": "05_validate_invoice.js",
		"role": "Seller",
		"description": "Uploads the cached invoice XML to POST /v1.beta/validation_reports.",
		"method": "pdp_integration.superpdp_functions.run_validate_invoice",
	},
	{
		"id": "06_list_buyer_invoices",
		"label": "List Buyer Invoices",
		"file": "06_list_buyer_invoices.js",
		"role": "Buyer",
		"description": "Lists invoices visible to the buyer (GET /v1.beta/invoices?order=desc).",
		"method": "pdp_integration.superpdp_functions.run_list_buyer_invoices",
	},
	{
		"id": "07_send_invoice",
		"label": "Send Invoice",
		"file": "07_send_invoice.js",
		"role": "Seller",
		"description": "Sends the cached invoice XML (POST /v1.beta/invoices) as the seller.",
		"method": "pdp_integration.superpdp_functions.run_send_invoice",
	},
	{
		"id": "08_check_received_invoice",
		"label": "Check Received Invoice (Buyer)",
		"file": "08_check_received_invoice.js",
		"role": "Buyer",
		"description": "Checks the buyer inbox for the latest received invoice(s).",
		"method": "pdp_integration.superpdp_functions.run_check_received_invoice",
	},
	{
		"id": "09_check_invoice_status",
		"label": "Check Invoice Status (Seller)",
		"file": "09_check_invoice_status.js",
		"role": "Seller",
		"description": "Polls GET /v1.beta/invoices/{id} for the last uploaded invoice's processing status.",
		"method": "pdp_integration.superpdp_functions.run_check_invoice_status",
	},
	{
		"id": "10_send_paid_event",
		"label": 'Send "Encaissee" Paid Event',
		"file": "10_send_paid_event.js",
		"role": "Seller",
		"description": "Sends a fr:212 (Encaissee) status event for the last uploaded invoice.",
		"method": "pdp_integration.superpdp_functions.run_send_paid_event",
	},
]

RECOMMENDED_ORDER = [item["id"] for item in FUNCTION_REGISTRY]


@frappe.whitelist()
def get_function_registry():
	return FUNCTION_REGISTRY


@frappe.whitelist()
def get_settings_status():
	from pdp_integration.pdp_client import get_settings

	settings = get_settings()
	seller_configured = bool(settings.get("burgerqueen_client_id")) and bool(
		settings.get_password("burgerqueen_client_secret", raise_exception=False)
	)
	buyer_configured = bool(settings.get("tricatel_client_id")) and bool(
		settings.get_password("tricatel_client_secret", raise_exception=False)
	)
	return {
		"endpoint": settings.get("superpdp_endpoint"),
		"seller_configured": seller_configured,
		"buyer_configured": buyer_configured,
	}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _cache_key(name):
	return f"pdp_integration:{name}:{frappe.session.user}"


def _cache_set(name, value):
	frappe.cache().set_value(_cache_key(name), value, expires_in_sec=CACHE_TTL)


def _cache_get(name):
	return frappe.cache().get_value(_cache_key(name))


def _safe_json(text):
	if text is None:
		return None
	try:
		return json.loads(text)
	except (ValueError, TypeError):
		return text


def _result(ok, http_status=None, response=None, error=None):
	return {"ok": bool(ok), "http_status": http_status, "response": response, "error": error}


def _to_log_text(value):
	if value is None:
		return None
	if isinstance(value, (dict, list)):
		try:
			return json.dumps(value, indent=2, ensure_ascii=False)[:100000]
		except Exception:
			return str(value)[:100000]
	return str(value)[:100000]


def _log(function_id, function_label, result, invoice_doctype=None, invoice=None, role=None, request_summary=None, superpdp_invoice_id=None):
	try:
		frappe.get_doc(
			{
				"doctype": "Super PDP Invoice Log",
				"invoice_doctype": invoice_doctype,
				"invoice": invoice,
				"role": role,
				"function_id": function_id,
				"function_label": function_label,
				"status": "Success" if result.get("ok") else "Failed",
				"http_status": result.get("http_status"),
				"request_summary": request_summary,
				"response": _to_log_text(result.get("response")),
				"error": result.get("error"),
				"superpdp_invoice_id": superpdp_invoice_id,
				"executed_by": frappe.session.user,
				"executed_on": now_datetime(),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "SuperPDP Log Error")


def _function_meta(function_id):
	for item in FUNCTION_REGISTRY:
		if item["id"] == function_id:
			return item
	return {"label": function_id}


# ---------------------------------------------------------------------------
# 01 - seller token
# ---------------------------------------------------------------------------

def _step_seller_token():
	client_id, client_secret = get_seller_credentials()
	ok, status, body, data, err = request_token(client_id, client_secret)
	if ok:
		_cache_set("seller_token", data.get("access_token"))
		return _result(True, status, {"token_type": data.get("token_type", "bearer"), "expires_in": data.get("expires_in"), "access_token": "***redacted***"})
	return _result(False, status, _safe_json(body), err)


@frappe.whitelist()
def run_seller_token(invoice_doctype=None, invoice=None):
	result = _step_seller_token()
	_log("01_seller_token", "Seller OAuth Token", result, invoice_doctype, invoice, "Seller", "POST /oauth2/token (seller credentials)")
	return result


# ---------------------------------------------------------------------------
# 02 - buyer token
# ---------------------------------------------------------------------------

def _step_buyer_token():
	client_id, client_secret = get_buyer_credentials()
	ok, status, body, data, err = request_token(client_id, client_secret)
	if ok:
		_cache_set("buyer_token", data.get("access_token"))
		return _result(True, status, {"token_type": data.get("token_type", "bearer"), "expires_in": data.get("expires_in"), "access_token": "***redacted***"})
	return _result(False, status, _safe_json(body), err)


@frappe.whitelist()
def run_buyer_token(invoice_doctype=None, invoice=None):
	result = _step_buyer_token()
	_log("02_buyer_token", "Buyer OAuth Token", result, invoice_doctype, invoice, "Buyer", "POST /oauth2/token (buyer credentials)")
	return result


# ---------------------------------------------------------------------------
# 03 - seller company
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_seller_company(invoice_doctype=None, invoice=None):
	try:
		token = get_seller_token()
	except SuperPDPError as exc:
		result = _result(False, exc.http_status, None, str(exc))
		_log("03_seller_company", "Seller Company Info", result, invoice_doctype, invoice, "Seller", "GET /v1.beta/companies/me")
		return result

	ok, status, text, err = do_request("GET", "/v1.beta/companies/me", headers={"Authorization": f"Bearer {token}"})
	result = _result(ok, status, _safe_json(text), err)
	_log("03_seller_company", "Seller Company Info", result, invoice_doctype, invoice, "Seller", "GET /v1.beta/companies/me")
	return result


# ---------------------------------------------------------------------------
# 04 - generate test invoice
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_generate_invoice(invoice_doctype=None, invoice=None):
	try:
		token = get_seller_token()
	except SuperPDPError as exc:
		result = _result(False, exc.http_status, None, str(exc))
		_log("04_generate_invoice", "Generate Test Invoice", result, invoice_doctype, invoice, "Seller", "GET /v1.beta/invoices/generate_test_invoice?format=ubl")
		return result

	ok, status, text, err = do_request(
		"GET",
		"/v1.beta/invoices/generate_test_invoice?format=ubl",
		headers={"Authorization": f"Bearer {token}"},
	)
	if ok:
		_cache_set("test_invoice_xml", text)
		preview = text[:2000] + ("... (truncated)" if len(text) > 2000 else "")
		result = _result(True, status, preview)
	else:
		result = _result(False, status, text, err)
	_log("04_generate_invoice", "Generate Test Invoice", result, invoice_doctype, invoice, "Seller", "GET /v1.beta/invoices/generate_test_invoice?format=ubl")
	return result


# ---------------------------------------------------------------------------
# 05 - validate invoice
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_validate_invoice(invoice_doctype=None, invoice=None):
	xml = _cache_get("test_invoice_xml")
	if not xml:
		result = _result(False, None, None, "No cached test invoice XML. Run '04 Generate Test Invoice' first.")
		_log("05_validate_invoice", "Validate Invoice", result, invoice_doctype, invoice, "Seller", "POST /v1.beta/validation_reports")
		return result

	try:
		token = get_seller_token()
	except SuperPDPError as exc:
		result = _result(False, exc.http_status, None, str(exc))
		_log("05_validate_invoice", "Validate Invoice", result, invoice_doctype, invoice, "Seller", "POST /v1.beta/validation_reports")
		return result

	endpoint = get_endpoint()
	try:
		response = requests.post(
			f"{endpoint}/v1.beta/validation_reports",
			headers={"Authorization": f"Bearer {token}"},
			files={"file": ("test_invoice.xml", xml.encode("utf-8"), "application/xml")},
			timeout=30,
		)
	except requests.RequestException as exc:
		result = _result(False, None, None, str(exc))
		_log("05_validate_invoice", "Validate Invoice", result, invoice_doctype, invoice, "Seller", "POST /v1.beta/validation_reports")
		return result

	body = response.text
	if not response.ok:
		result = _result(False, response.status_code, _safe_json(body), f"HTTP {response.status_code}: {body}")
	else:
		data = _safe_json(body)
		is_valid = None
		if isinstance(data, dict):
			items = data.get("data") or []
			if items:
				is_valid = items[0].get("is_valid")
		result = _result(True, response.status_code, {"is_valid": is_valid, "raw": data})
	_log("05_validate_invoice", "Validate Invoice", result, invoice_doctype, invoice, "Seller", "POST /v1.beta/validation_reports")
	return result


# ---------------------------------------------------------------------------
# 06 - list buyer invoices
# ---------------------------------------------------------------------------

def _fetch_buyer_invoices(starting_after_id=None):
	token = get_buyer_token()
	path = "/v1.beta/invoices?order=desc"
	if starting_after_id:
		path = f"/v1.beta/invoices?starting_after_id={starting_after_id}"
	ok, status, text, err = do_request("GET", path, headers={"Authorization": f"Bearer {token}"})
	return ok, status, text, err


@frappe.whitelist()
def run_list_buyer_invoices(invoice_doctype=None, invoice=None):
	try:
		ok, status, text, err = _fetch_buyer_invoices()
	except SuperPDPError as exc:
		result = _result(False, exc.http_status, None, str(exc))
		_log("06_list_buyer_invoices", "List Buyer Invoices", result, invoice_doctype, invoice, "Buyer", "GET /v1.beta/invoices?order=desc")
		return result

	if ok:
		data = _safe_json(text)
		items = data.get("data", []) if isinstance(data, dict) else []
		summary = {
			"count": len(items),
			"invoices": [{"id": inv.get("id"), "number": inv.get("number")} for inv in items[:20]],
		}
		result = _result(True, status, summary)
	else:
		result = _result(False, status, _safe_json(text), err)
	_log("06_list_buyer_invoices", "List Buyer Invoices", result, invoice_doctype, invoice, "Buyer", "GET /v1.beta/invoices?order=desc")
	return result


# ---------------------------------------------------------------------------
# 07 - send invoice
# ---------------------------------------------------------------------------

def _send_invoice_xml(xml):
	"""Shared implementation: POST an arbitrary UBL invoice XML to
	SuperPDP as the seller. Returns (ok, http_status, response_or_text, error, superpdp_invoice_id).
	Used both by the sandbox-cached flow (run_send_invoice) and by the
	real-ERPNext-data flow (run_send_custom_invoice)."""
	try:
		token = get_seller_token()
	except SuperPDPError as exc:
		return False, exc.http_status, None, str(exc), None

	ok, status, text, err = do_request(
		"POST",
		"/v1.beta/invoices",
		headers={"Authorization": f"Bearer {token}", "Content-Type": "application/xml"},
		data=xml.encode("utf-8"),
	)
	superpdp_invoice_id = None
	if ok:
		data = _safe_json(text)
		if isinstance(data, dict) and data.get("id"):
			_cache_set("uploaded_invoice", json.dumps(data))
			superpdp_invoice_id = data.get("id")
		return True, status, data, None, superpdp_invoice_id
	return False, status, _safe_json(text), err, None


@frappe.whitelist()
def run_send_invoice(invoice_doctype=None, invoice=None):
	xml = _cache_get("test_invoice_xml")
	if not xml:
		result = _result(False, None, None, "No cached test invoice XML. Run '04 Generate Test Invoice' first.")
		_log("07_send_invoice", "Send Invoice", result, invoice_doctype, invoice, "Seller", "POST /v1.beta/invoices")
		return result

	ok, status, response, err, superpdp_invoice_id = _send_invoice_xml(xml)
	result = _result(ok, status, response, err)
	_log(
		"07_send_invoice",
		"Send Invoice",
		result,
		invoice_doctype,
		invoice,
		"Seller",
		"POST /v1.beta/invoices",
		superpdp_invoice_id=superpdp_invoice_id,
	)
	return result


@frappe.whitelist()
def run_send_custom_invoice(xml, invoice_doctype=None, invoice=None, request_summary=None):
	"""Same SuperPDP call as run_send_invoice (function 07), but for a
	caller-supplied XML (e.g. a real UBL invoice built from an ERPNext
	Sales Invoice by ubl_builder.build_invoice_xml) instead of the
	cached sandbox test invoice."""
	ok, status, response, err, superpdp_invoice_id = _send_invoice_xml(xml)
	result = _result(ok, status, response, err)
	_log(
		"07_send_invoice",
		"Send Invoice",
		result,
		invoice_doctype,
		invoice,
		"Seller",
		request_summary or "POST /v1.beta/invoices (real ERPNext invoice data)",
		superpdp_invoice_id=superpdp_invoice_id,
	)
	return result


# ---------------------------------------------------------------------------
# 08 - check received invoice (buyer inbox)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_check_received_invoice(invoice_doctype=None, invoice=None):
	try:
		ok, status, text, err = _fetch_buyer_invoices()
	except SuperPDPError as exc:
		result = _result(False, exc.http_status, None, str(exc))
		_log("08_check_received_invoice", "Check Received Invoice (Buyer)", result, invoice_doctype, invoice, "Buyer", "GET /v1.beta/invoices?order=desc")
		return result

	if ok:
		data = _safe_json(text)
		items = data.get("data", []) if isinstance(data, dict) else []
		result = _result(
			True,
			status,
			{
				"count": len(items),
				"latest_invoice": items[0] if items else None,
			},
		)
	else:
		result = _result(False, status, _safe_json(text), err)
	_log("08_check_received_invoice", "Check Received Invoice (Buyer)", result, invoice_doctype, invoice, "Buyer", "GET /v1.beta/invoices?order=desc")
	return result


# ---------------------------------------------------------------------------
# 09 - check invoice status (seller)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_check_invoice_status(invoice_doctype=None, invoice=None):
	uploaded_raw = _cache_get("uploaded_invoice")
	if not uploaded_raw:
		result = _result(False, None, None, "No cached uploaded invoice. Run '07 Send Invoice' first.")
		_log("09_check_invoice_status", "Check Invoice Status (Seller)", result, invoice_doctype, invoice, "Seller", "GET /v1.beta/invoices/{id}")
		return result

	uploaded = json.loads(uploaded_raw)
	invoice_id = uploaded.get("id")

	try:
		token = get_seller_token()
	except SuperPDPError as exc:
		result = _result(False, exc.http_status, None, str(exc))
		_log("09_check_invoice_status", "Check Invoice Status (Seller)", result, invoice_doctype, invoice, "Seller", f"GET /v1.beta/invoices/{invoice_id}")
		return result

	ok, status, text, err = do_request(
		"GET", f"/v1.beta/invoices/{invoice_id}", headers={"Authorization": f"Bearer {token}"}
	)
	if ok:
		data = _safe_json(text)
		en_invoice = data.get("en_invoice") if isinstance(data, dict) else None
		result = _result(True, status, {"invoice_id": invoice_id, "en_invoice": en_invoice, "processed": bool(en_invoice)})
	else:
		result = _result(False, status, _safe_json(text), err)
	_log("09_check_invoice_status", "Check Invoice Status (Seller)", result, invoice_doctype, invoice, "Seller", f"GET /v1.beta/invoices/{invoice_id}")
	return result


# ---------------------------------------------------------------------------
# 10 - send paid ("Encaissee") event
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_send_paid_event(invoice_doctype=None, invoice=None):
	uploaded_raw = _cache_get("uploaded_invoice")
	if not uploaded_raw:
		result = _result(False, None, None, "No cached uploaded invoice. Run '07 Send Invoice' first.")
		_log("10_send_paid_event", 'Send "Encaissee" Paid Event', result, invoice_doctype, invoice, "Seller", "POST /v1.beta/invoice_events")
		return result

	uploaded = json.loads(uploaded_raw)
	invoice_id = uploaded.get("id")

	try:
		token = get_seller_token()
	except SuperPDPError as exc:
		result = _result(False, exc.http_status, None, str(exc))
		_log("10_send_paid_event", 'Send "Encaissee" Paid Event', result, invoice_doctype, invoice, "Seller", "POST /v1.beta/invoice_events")
		return result

	# Same demo payload used in the original 10_send_paid_event.js / README.
	payload = {
		"invoice_id": invoice_id,
		"status_code": "fr:212",
		"details": [
			{
				"amounts": [
					{
						"net_amount": "1800.00",
						"currency_code": "EUR",
						"type_code": "MEN",
						"vat_rate": "20.0",
						"date": "2026-03-31",
					},
					{
						"net_amount": "63.79",
						"currency_code": "EUR",
						"type_code": "MEN",
						"vat_rate": "5.5",
						"date": "2026-03-31",
					},
				]
			}
		],
	}

	ok, status, text, err = do_request(
		"POST",
		"/v1.beta/invoice_events",
		headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
		data=json.dumps(payload),
	)
	result = _result(ok, status, _safe_json(text) if ok else _safe_json(text), err)
	_log("10_send_paid_event", 'Send "Encaissee" Paid Event', result, invoice_doctype, invoice, "Seller", "POST /v1.beta/invoice_events")
	return result


# ---------------------------------------------------------------------------
# Dispatch by id (used by the "Run all" sequence in the console)
# ---------------------------------------------------------------------------

_DISPATCH = {
	"01_seller_token": run_seller_token,
	"02_buyer_token": run_buyer_token,
	"03_seller_company": run_seller_company,
	"04_generate_invoice": run_generate_invoice,
	"05_validate_invoice": run_validate_invoice,
	"06_list_buyer_invoices": run_list_buyer_invoices,
	"07_send_invoice": run_send_invoice,
	"08_check_received_invoice": run_check_received_invoice,
	"09_check_invoice_status": run_check_invoice_status,
	"10_send_paid_event": run_send_paid_event,
}


@frappe.whitelist()
def run_function(function_id, invoice_doctype=None, invoice=None):
	fn = _DISPATCH.get(function_id)
	if not fn:
		frappe.throw(f"Unknown SuperPDP function: {function_id}")
	return fn(invoice_doctype=invoice_doctype, invoice=invoice)
