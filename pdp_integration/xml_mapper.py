# -*- coding: utf-8 -*-
"""
The mapping-driven engine behind the "Super PDP XML Configuration" page
and behind the real "Send to SuperPDP" call.

Every value that ends up in the generated XML is resolved through the
"Super PDP XML Field Mapping" table (ERPNext doctype + field + an
optional transformation, or an explicit static value, or an engine
computation for values that are genuinely derived rather than copied -
e.g. a tax subtotal, a line number, a SIREN extracted from a SIRET).
Nothing here reads ERPNext data straight into the XML the way the old
`ubl_builder.py` did - that logic now lives here as the *default seed*
for the mapping table (see xml_mapping_defaults.py) and as reusable
helper functions, so behaviour is preserved, not duplicated.

Two entry points matter:
  - resolve_all(invoice)   -> the full mapping + live-value report used
                               by the configuration page (preview,
                               missing-field detection, validation).
  - render_invoice_xml(invoice) -> the actual XML string, built from the
                               same resolved values. This is what
                               invoices.py sends to SuperPDP - there is
                               only one generation path.

The final XML re-uses the exact nested UBL structure/namespaces that
were already hand-verified (well-formed, matches the SuperPDP sample) -
only the *values* plugged into that structure are now mapping-driven.
"""

import json
from xml.sax.saxutils import escape as xml_escape

import frappe
from frappe.utils import flt, cint, getdate

DEFAULT_TEMPLATE_DOCTYPE = "Super PDP XML Template"
MAPPING_DOCTYPE = "Super PDP XML Field Mapping"

UBL_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"

UOM_CODE_MAP = {
	"nos": "C62", "unit": "C62", "each": "C62",
	"kg": "KGM", "kilogram": "KGM", "gram": "GRM", "g": "GRM",
	"litre": "LTR", "liter": "LTR", "l": "LTR",
	"metre": "MTR", "meter": "MTR", "m": "MTR",
	"hour": "HUR", "hr": "HUR", "day": "DAY", "box": "BX", "pair": "PR",
}

STATUS_MAPPED = "Mapped"
STATUS_COMPUTED = "Computed"
STATUS_STATIC = "Static"
STATUS_MISSING_REQUIRED = "Missing Required"
STATUS_OPTIONAL_UNMAPPED = "Optional Unmapped"
STATUS_INVALID = "Invalid"

OK_STATUSES = (STATUS_MAPPED, STATUS_COMPUTED, STATUS_STATIC)


class UBLBuildError(frappe.ValidationError):
	pass


# ---------------------------------------------------------------------------
# small value helpers (ported from the old ubl_builder.py, reused here)
# ---------------------------------------------------------------------------

def _e(value):
	return xml_escape("" if value is None else str(value))


def siren_from_siret(siret):
	siret = (siret or "").replace(" ", "")
	return siret[:9] if len(siret) == 14 else siret


def country_code(country_name):
	if not country_name:
		return "FR"
	code = frappe.db.get_value("Country", country_name, "code")
	return (code or "FR").upper()


def uom_code(uom):
	if not uom:
		return "C62"
	return UOM_CODE_MAP.get(uom.strip().lower(), "C62")


def item_tax_rate_percent(item, invoice):
	raw = item.get("item_tax_rate")
	if raw:
		try:
			rates = json.loads(raw)
			if rates:
				return flt(sum(rates.values()))
		except (ValueError, TypeError):
			pass
	net_total = flt(invoice.get("net_total"))
	if net_total:
		return flt(flt(invoice.get("total_taxes_and_charges")) / net_total * 100)
	return 0.0


# ---------------------------------------------------------------------------
# transformations (curated, no arbitrary code execution)
# ---------------------------------------------------------------------------

def _t_none(v, ctx):
	return v


def _t_currency_code(v, ctx):
	return (v or "").upper() or None


def _t_date(v, ctx):
	if not v:
		return None
	return getdate(v).strftime("%Y-%m-%d")


def _t_number2(v, ctx):
	if v in (None, ""):
		return None
	return f"{flt(v):.2f}"


def _t_number3(v, ctx):
	if v in (None, ""):
		return None
	return f"{flt(v):.3f}"


def _t_percent1(v, ctx):
	if v in (None, ""):
		return None
	return f"{flt(v):.1f}"


def _t_country_code(v, ctx):
	return country_code(v)


def _t_siren_from_siret(v, ctx):
	return siren_from_siret(v) or None


def _t_uom_code(v, ctx):
	return uom_code(v)


def _t_invoice_type_code(v, ctx):
	return "381" if cint(v) else "380"


def _t_strip_html(v, ctx):
	text = frappe.utils.strip_html(v or "").strip()
	return text or None


TRANSFORMATIONS = {
	"None": _t_none,
	"Currency Code (ISO)": _t_currency_code,
	"Date (YYYY-MM-DD)": _t_date,
	"Number (2 decimals)": _t_number2,
	"Number (3 decimals)": _t_number3,
	"Percent (1 decimal)": _t_percent1,
	"Country Code (ISO)": _t_country_code,
	"SIREN from SIRET": _t_siren_from_siret,
	"UOM Code (UN/ECE)": _t_uom_code,
	"Invoice Type Code (380/381)": _t_invoice_type_code,
	"Strip HTML": _t_strip_html,
}

TRANSFORMATION_CHOICES = list(TRANSFORMATIONS.keys()) + ["Static Value", "Computed by Engine"]


# ---------------------------------------------------------------------------
# computed values (genuinely derived, not a single field copy)
# ---------------------------------------------------------------------------

def _computed_buyer_siret(ctx):
	return ctx.get("_buyer_siret")


def _computed_buyer_siren(ctx):
	return siren_from_siret(ctx.get("_buyer_siret")) or None


def _computed_line_id(ctx):
	idx = ctx.get("_current_index")
	return f"{idx:03d}" if idx else None


def _computed_line_tax_category_id(ctx):
	rate = flt(ctx.get("_current_item_rate"))
	return "Z" if rate == 0 else "S"


def _computed_line_tax_percent(ctx):
	item = ctx.get("_current_item") or {}
	invoice = ctx.get("Sales Invoice")
	rate = flt(item_tax_rate_percent(item, invoice))
	ctx["_current_item_rate"] = rate
	return f"{rate:.1f}"


def _computed_subtotal_taxable(ctx):
	bucket = ctx.get("_current_bucket") or {}
	return f"{flt(bucket.get('taxable')):.2f}"


def _computed_subtotal_tax(ctx):
	bucket = ctx.get("_current_bucket") or {}
	return f"{flt(bucket.get('tax')):.2f}"


def _computed_subtotal_category_id(ctx):
	rate = flt(ctx.get("_current_rate"))
	return "Z" if rate == 0 else "S"


def _computed_subtotal_percent(ctx):
	rate = flt(ctx.get("_current_rate"))
	return f"{rate:.1f}"


_COMPUTED = {
	"AccountingCustomerParty/Party/EndpointID": _computed_buyer_siret,
	"AccountingCustomerParty/Party/PartyIdentification/ID": _computed_buyer_siren,
	"AccountingCustomerParty/Party/PartyLegalEntity/CompanyID": _computed_buyer_siren,
	"InvoiceLine/ID": _computed_line_id,
	"InvoiceLine/Item/ClassifiedTaxCategory/ID": _computed_line_tax_category_id,
	"InvoiceLine/Item/ClassifiedTaxCategory/Percent": _computed_line_tax_percent,
	"TaxTotal/TaxSubtotal/TaxableAmount": _computed_subtotal_taxable,
	"TaxTotal/TaxSubtotal/TaxAmount": _computed_subtotal_tax,
	"TaxTotal/TaxSubtotal/TaxCategory/ID": _computed_subtotal_category_id,
	"TaxTotal/TaxSubtotal/TaxCategory/Percent": _computed_subtotal_percent,
}


# ---------------------------------------------------------------------------
# mapping table access
# ---------------------------------------------------------------------------

_MAPPING_FIELDS = [
	"name", "xml_path", "section", "scope", "is_attribute", "attribute_name",
	"erpnext_doctype", "erpnext_field", "data_type", "required",
	"transformation", "static_value", "sample_value", "notes", "template",
]


def get_default_template_name():
	name = frappe.db.get_value(DEFAULT_TEMPLATE_DOCTYPE, {"is_default": 1}, "name")
	if not name:
		frappe.throw(
			"No default Super PDP XML Template is configured. Open 'Super PDP XML Template' and mark one as default.",
			UBLBuildError,
		)
	return name


def get_mapping_rows(template_name=None):
	template_name = template_name or get_default_template_name()
	rows = frappe.get_all(
		MAPPING_DOCTYPE,
		filters={"template": template_name},
		fields=_MAPPING_FIELDS,
		order_by="section asc, xml_path asc",
	)
	return rows


def get_mapping_by_path(template_name=None):
	return {row["xml_path"]: row for row in get_mapping_rows(template_name)}


# ---------------------------------------------------------------------------
# context + field resolution
# ---------------------------------------------------------------------------

def build_context(invoice):
	if invoice.doctype != "Sales Invoice":
		frappe.throw("Real UBL generation only supports Sales Invoice (seller role).", UBLBuildError)

	settings = frappe.get_single("Super PDP Settings")
	company_doc = frappe.get_cached_doc("Company", invoice.company)
	customer_doc = frappe.get_cached_doc("Customer", invoice.customer)

	buyer_siret = (customer_doc.get("custom_siret") or settings.get("default_buyer_siret") or "").strip() or None

	return {
		"Sales Invoice": invoice,
		"Company": company_doc,
		"Customer": customer_doc,
		"Super PDP Settings": settings,
		"_buyer_siret": buyer_siret,
	}


def _doc_get(doc, field):
	if doc is None:
		return None
	try:
		return doc.get(field)
	except AttributeError:
		return None


def resolve_field(row, context):
	"""Resolve one mapping row against context. Returns a dict describing
	xml_path, section, scope, source, raw_value, final_value, status,
	message - everything the UI table needs, and everything the XML
	renderer needs."""
	xml_path = row["xml_path"]
	required = bool(row.get("required"))
	transformation = row.get("transformation") or "None"

	out = {
		"xml_path": xml_path,
		"section": row.get("section"),
		"scope": row.get("scope") or "Invoice",
		"is_attribute": bool(row.get("is_attribute")),
		"attribute_name": row.get("attribute_name"),
		"required": required,
		"erpnext_doctype": row.get("erpnext_doctype"),
		"erpnext_field": row.get("erpnext_field"),
		"transformation": transformation,
		"data_type": row.get("data_type"),
		"raw_value": None,
		"final_value": None,
		"status": STATUS_OPTIONAL_UNMAPPED,
		"message": None,
	}

	if transformation == "Static Value":
		val = row.get("static_value")
		out["raw_value"] = val
		out["final_value"] = val
		out["status"] = STATUS_STATIC if val not in (None, "") else (
			STATUS_MISSING_REQUIRED if required else STATUS_OPTIONAL_UNMAPPED
		)
		out["source"] = "Static value"
		return out

	if transformation == "Computed by Engine":
		fn = _COMPUTED.get(xml_path)
		if not fn:
			out["status"] = STATUS_MISSING_REQUIRED if required else STATUS_OPTIONAL_UNMAPPED
			out["message"] = "No computation is defined for this path."
			out["source"] = "Computed (undefined)"
			return out
		try:
			val = fn(context)
		except Exception as exc:  # noqa: BLE001
			out["status"] = STATUS_INVALID
			out["message"] = str(exc)
			out["source"] = "Computed"
			return out
		out["raw_value"] = val
		out["final_value"] = val
		out["status"] = STATUS_COMPUTED if val not in (None, "") else (
			STATUS_MISSING_REQUIRED if required else STATUS_OPTIONAL_UNMAPPED
		)
		out["source"] = "Computed by engine"
		return out

	doctype = row.get("erpnext_doctype")
	field = row.get("erpnext_field")
	if not doctype or not field:
		out["status"] = STATUS_MISSING_REQUIRED if required else STATUS_OPTIONAL_UNMAPPED
		out["message"] = "No ERPNext field configured."
		out["source"] = None
		return out

	if doctype == "Sales Invoice Item":
		doc = context.get("_current_item")
	else:
		doc = context.get(doctype)

	if doc is None:
		out["status"] = STATUS_INVALID
		out["message"] = f"{doctype} is not available in this context."
		out["source"] = f"{doctype}.{field}"
		return out

	raw = _doc_get(doc, field)
	out["raw_value"] = raw
	out["source"] = f"{doctype}.{field}"

	transform_fn = TRANSFORMATIONS.get(transformation, _t_none)
	try:
		final = transform_fn(raw, context)
	except Exception as exc:  # noqa: BLE001
		out["status"] = STATUS_INVALID
		out["message"] = str(exc)
		return out

	out["final_value"] = final
	if final in (None, ""):
		out["status"] = STATUS_MISSING_REQUIRED if required else STATUS_OPTIONAL_UNMAPPED
	else:
		out["status"] = STATUS_MAPPED
	return out


# ---------------------------------------------------------------------------
# full resolution (drives the configuration page)
# ---------------------------------------------------------------------------

def resolve_all(invoice, template_name=None):
	mapping_rows = get_mapping_rows(template_name)
	context = build_context(invoice)

	invoice_rows = [r for r in mapping_rows if r["scope"] == "Invoice"]
	line_row_defs = [r for r in mapping_rows if r["scope"] == "InvoiceLine"]
	subtotal_row_defs = [r for r in mapping_rows if r["scope"] == "TaxSubtotal"]
	note_row_defs = [r for r in mapping_rows if r["scope"] == "Note"]

	resolved_invoice = [resolve_field(row, context) for row in invoice_rows]

	# Invoice lines - resolve every InvoiceLine-scoped field against every
	# real Sales Invoice Item, and build the tax-rate buckets while we're at it.
	rate_groups = {}
	lines = []
	currency = context["Sales Invoice"].currency
	for idx, item_doc in enumerate(invoice.items, start=1):
		item = item_doc.as_dict()
		item["currency"] = currency
		context["_current_item"] = item
		context["_current_index"] = idx
		rate = flt(item_tax_rate_percent(item, invoice))
		context["_current_item_rate"] = rate

		fields = [resolve_field(row, context) for row in line_row_defs]
		lines.append({"item_code": item.get("item_code"), "item_name": item.get("item_name"), "fields": fields})

		taxable = flt(item.get("net_amount") or item.get("amount"))
		bucket = rate_groups.setdefault(rate, {"taxable": 0.0, "tax": 0.0})
		bucket["taxable"] += taxable
		bucket["tax"] += taxable * rate / 100

	context.pop("_current_item", None)
	context.pop("_current_index", None)
	context.pop("_current_item_rate", None)

	tax_subtotals = []
	for rate in sorted(rate_groups.keys()):
		context["_current_rate"] = rate
		context["_current_bucket"] = rate_groups[rate]
		fields = [resolve_field(row, context) for row in subtotal_row_defs]
		tax_subtotals.append({"rate": rate, "fields": fields})
	context.pop("_current_rate", None)
	context.pop("_current_bucket", None)

	notes = [resolve_field(row, context) for row in note_row_defs]

	all_resolved = resolved_invoice + [f for l in lines for f in l["fields"]] + [f for t in tax_subtotals for f in t["fields"]] + notes
	blocking_errors = [
		f"{r['xml_path']}: {r['message'] or 'required but not mapped/empty'}"
		for r in all_resolved
		if r["status"] in (STATUS_MISSING_REQUIRED, STATUS_INVALID)
	]

	return {
		"invoice": invoice.name,
		"invoice_fields": resolved_invoice,
		"lines": lines,
		"tax_subtotals": tax_subtotals,
		"notes": notes,
		"can_send": len(blocking_errors) == 0,
		"blocking_errors": blocking_errors,
	}


# ---------------------------------------------------------------------------
# XML rendering (drives the real send + "Preview XML")
# ---------------------------------------------------------------------------

def _val(resolved_list, xml_path):
	for r in resolved_list:
		if r["xml_path"] == xml_path and not r["is_attribute"]:
			return r["final_value"]
	return None


def _attr(resolved_list, xml_path):
	for r in resolved_list:
		if r["xml_path"] == xml_path and r["is_attribute"]:
			return r["final_value"]
	return None


def _party_xml(tag, resolved, prefix):
	endpoint_id = _val(resolved, f"{prefix}/Party/EndpointID")
	endpoint_scheme = _attr(resolved, f"{prefix}/Party/EndpointID@schemeID") or "0225"
	country = _val(resolved, f"{prefix}/Party/PostalAddress/Country/IdentificationCode") or "FR"
	vat_number = _val(resolved, f"{prefix}/Party/PartyTaxScheme/CompanyID")
	reg_name = _val(resolved, f"{prefix}/Party/PartyLegalEntity/RegistrationName")
	legal_id = _val(resolved, f"{prefix}/Party/PartyLegalEntity/CompanyID")
	legal_scheme = _attr(resolved, f"{prefix}/Party/PartyLegalEntity/CompanyID@schemeID") or "0002"

	party_identification_xml = ""
	pid = _val(resolved, f"{prefix}/Party/PartyIdentification/ID")
	if pid:
		pid_scheme = _attr(resolved, f"{prefix}/Party/PartyIdentification/ID@schemeID") or "0225"
		party_identification_xml = (
			f'<cac:PartyIdentification xmlns:cac="{CAC_NS}">'
			f'<cbc:ID xmlns:cbc="{CBC_NS}" schemeID="{_e(pid_scheme)}">{_e(pid)}</cbc:ID>'
			f"</cac:PartyIdentification>"
		)

	tax_scheme_xml = (
		f'<cac:PartyTaxScheme xmlns:cac="{CAC_NS}">'
		f'<cbc:CompanyID xmlns:cbc="{CBC_NS}">{_e(vat_number)}</cbc:CompanyID>'
		f'<cac:TaxScheme xmlns:cac="{CAC_NS}"><cbc:ID xmlns:cbc="{CBC_NS}">VAT</cbc:ID></cac:TaxScheme>'
		f"</cac:PartyTaxScheme>"
		if vat_number
		else ""
	)

	return f"""
  <cac:{tag} xmlns:cac="{CAC_NS}">
    <cac:Party xmlns:cac="{CAC_NS}">
      <cbc:EndpointID xmlns:cbc="{CBC_NS}" schemeID="{_e(endpoint_scheme)}">{_e(endpoint_id)}</cbc:EndpointID>
      {party_identification_xml}
      <cac:PostalAddress xmlns:cac="{CAC_NS}">
        <cac:Country xmlns:cac="{CAC_NS}">
          <cbc:IdentificationCode xmlns:cbc="{CBC_NS}">{_e(country)}</cbc:IdentificationCode>
        </cac:Country>
      </cac:PostalAddress>
      {tax_scheme_xml}
      <cac:PartyLegalEntity xmlns:cac="{CAC_NS}">
        <cbc:RegistrationName xmlns:cbc="{CBC_NS}">{_e(reg_name)}</cbc:RegistrationName>
        <cbc:CompanyID xmlns:cbc="{CBC_NS}" schemeID="{_e(legal_scheme)}">{_e(legal_id)}</cbc:CompanyID>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:{tag}>""".strip("\n")


def _delivery_xml(resolved):
	date = _val(resolved, "Delivery/ActualDeliveryDate")
	country = _val(resolved, "Delivery/DeliveryLocation/Address/Country/IdentificationCode")
	if not date and not country:
		return ""
	country_xml = (
		f'<cac:DeliveryLocation xmlns:cac="{CAC_NS}"><cac:Address xmlns:cac="{CAC_NS}">'
		f'<cac:Country xmlns:cac="{CAC_NS}"><cbc:IdentificationCode xmlns:cbc="{CBC_NS}">{_e(country)}</cbc:IdentificationCode></cac:Country>'
		f"</cac:Address></cac:DeliveryLocation>"
		if country
		else ""
	)
	date_xml = f'<cbc:ActualDeliveryDate xmlns:cbc="{CBC_NS}">{_e(date)}</cbc:ActualDeliveryDate>' if date else ""
	return f'\n  <cac:Delivery xmlns:cac="{CAC_NS}">{date_xml}{country_xml}</cac:Delivery>'


def _invoice_line_xml(resolved):
	line_id = _val(resolved, "InvoiceLine/ID")
	qty = _val(resolved, "InvoiceLine/InvoicedQuantity")
	unit_code = _attr(resolved, "InvoiceLine/InvoicedQuantity@unitCode") or "C62"
	line_amount = _val(resolved, "InvoiceLine/LineExtensionAmount")
	line_currency = _attr(resolved, "InvoiceLine/LineExtensionAmount@currencyID")
	name = _val(resolved, "InvoiceLine/Item/Name")
	description = _val(resolved, "InvoiceLine/Item/Description")
	tax_id = _val(resolved, "InvoiceLine/Item/ClassifiedTaxCategory/ID")
	tax_pct = _val(resolved, "InvoiceLine/Item/ClassifiedTaxCategory/Percent")
	price = _val(resolved, "InvoiceLine/Price/PriceAmount")
	price_currency = _attr(resolved, "InvoiceLine/Price/PriceAmount@currencyID")

	# Only emit a separate <Description> when it adds information beyond the name.
	if description and name and description.strip().lower() == name.strip().lower():
		description = None

	description_xml = (
		f'<cbc:Description xmlns:cbc="{CBC_NS}">{_e(description[:1000])}</cbc:Description>' if description else ""
	)

	return f"""
  <cac:InvoiceLine xmlns:cac="{CAC_NS}">
    <cbc:ID xmlns:cbc="{CBC_NS}">{_e(line_id)}</cbc:ID>
    <cbc:InvoicedQuantity xmlns:cbc="{CBC_NS}" unitCode="{_e(unit_code)}">{_e(qty)}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(line_currency)}">{_e(line_amount)}</cbc:LineExtensionAmount>
    <cac:Item xmlns:cac="{CAC_NS}">
      {description_xml}
      <cbc:Name xmlns:cbc="{CBC_NS}">{_e(name)}</cbc:Name>
      <cac:ClassifiedTaxCategory xmlns:cac="{CAC_NS}">
        <cbc:ID xmlns:cbc="{CBC_NS}">{_e(tax_id)}</cbc:ID>
        <cbc:Percent xmlns:cbc="{CBC_NS}">{_e(tax_pct)}</cbc:Percent>
        <cac:TaxScheme xmlns:cac="{CAC_NS}"><cbc:ID xmlns:cbc="{CBC_NS}">VAT</cbc:ID></cac:TaxScheme>
      </cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price xmlns:cac="{CAC_NS}">
      <cbc:PriceAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(price_currency)}">{_e(price)}</cbc:PriceAmount>
    </cac:Price>
  </cac:InvoiceLine>""".strip("\n")


def _tax_subtotal_xml(resolved):
	taxable = _val(resolved, "TaxTotal/TaxSubtotal/TaxableAmount")
	taxable_currency = _attr(resolved, "TaxTotal/TaxSubtotal/TaxableAmount@currencyID")
	tax_amount = _val(resolved, "TaxTotal/TaxSubtotal/TaxAmount")
	tax_currency = _attr(resolved, "TaxTotal/TaxSubtotal/TaxAmount@currencyID")
	category_id = _val(resolved, "TaxTotal/TaxSubtotal/TaxCategory/ID")
	percent = _val(resolved, "TaxTotal/TaxSubtotal/TaxCategory/Percent")

	return f"""
    <cac:TaxSubtotal xmlns:cac="{CAC_NS}">
      <cbc:TaxableAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(taxable_currency)}">{_e(taxable)}</cbc:TaxableAmount>
      <cbc:TaxAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(tax_currency)}">{_e(tax_amount)}</cbc:TaxAmount>
      <cac:TaxCategory xmlns:cac="{CAC_NS}">
        <cbc:ID xmlns:cbc="{CBC_NS}">{_e(category_id)}</cbc:ID>
        <cbc:Percent xmlns:cbc="{CBC_NS}">{_e(percent)}</cbc:Percent>
        <cac:TaxScheme xmlns:cac="{CAC_NS}"><cbc:ID xmlns:cbc="{CBC_NS}">VAT</cbc:ID></cac:TaxScheme>
      </cac:TaxCategory>
    </cac:TaxSubtotal>""".strip("\n")


def render_invoice_xml(invoice, template_name=None):
	"""invoice: a loaded ERPNext Sales Invoice document.

	Returns (xml_string, meta_dict). Raises UBLBuildError (with every
	blocking problem listed) if a required field could not be resolved -
	the caller should show that to the admin rather than sending a
	half-built invoice.
	"""
	resolution = resolve_all(invoice, template_name)

	if not resolution["can_send"]:
		raise UBLBuildError(
			"Cannot build a valid invoice - required fields are missing or invalid:\n"
			+ "\n".join(f"- {e}" for e in resolution["blocking_errors"])
		)

	inv = resolution["invoice_fields"]

	issue_date = _val(inv, "IssueDate")
	due_date = _val(inv, "DueDate") or issue_date
	invoice_type_code = _val(inv, "InvoiceTypeCode")
	currency = _val(inv, "DocumentCurrencyCode")

	notes_xml = "".join(
		f'\n  <cbc:Note xmlns:cbc="{CBC_NS}">{_e(n["final_value"])}</cbc:Note>'
		for n in resolution["notes"]
		if n["final_value"]
	)

	lines_xml = "\n".join(_invoice_line_xml(l["fields"]) for l in resolution["lines"])
	tax_subtotals_xml = "\n".join(_tax_subtotal_xml(t["fields"]) for t in resolution["tax_subtotals"])

	total_tax_amount = _val(inv, "TaxTotal/TaxAmount")
	total_tax_currency = _attr(inv, "TaxTotal/TaxAmount@currencyID")

	net_total = _val(inv, "LegalMonetaryTotal/LineExtensionAmount")
	tax_excl = _val(inv, "LegalMonetaryTotal/TaxExclusiveAmount")
	tax_incl = _val(inv, "LegalMonetaryTotal/TaxInclusiveAmount")
	payable = _val(inv, "LegalMonetaryTotal/PayableAmount")
	monetary_currency = _attr(inv, "LegalMonetaryTotal/LineExtensionAmount@currencyID")

	xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="{UBL_NS}">
  <cbc:CustomizationID xmlns:cbc="{CBC_NS}">urn:cen.eu:en16931:2017</cbc:CustomizationID>
  <cbc:ProfileID xmlns:cbc="{CBC_NS}">M1</cbc:ProfileID>
  <cbc:ID xmlns:cbc="{CBC_NS}">{_e(_val(inv, "ID"))}</cbc:ID>
  <cbc:IssueDate xmlns:cbc="{CBC_NS}">{_e(issue_date)}</cbc:IssueDate>
  <cbc:DueDate xmlns:cbc="{CBC_NS}">{_e(due_date)}</cbc:DueDate>
  <cbc:InvoiceTypeCode xmlns:cbc="{CBC_NS}">{_e(invoice_type_code)}</cbc:InvoiceTypeCode>{notes_xml}
  <cbc:DocumentCurrencyCode xmlns:cbc="{CBC_NS}">{_e(currency)}</cbc:DocumentCurrencyCode>
{_party_xml("AccountingSupplierParty", inv, "AccountingSupplierParty")}
{_party_xml("AccountingCustomerParty", inv, "AccountingCustomerParty")}{_delivery_xml(inv)}
  <cac:TaxTotal xmlns:cac="{CAC_NS}">
    <cbc:TaxAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(total_tax_currency)}">{_e(total_tax_amount)}</cbc:TaxAmount>
{tax_subtotals_xml}
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal xmlns:cac="{CAC_NS}">
    <cbc:LineExtensionAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(monetary_currency)}">{_e(net_total)}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(monetary_currency)}">{_e(tax_excl)}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(monetary_currency)}">{_e(tax_incl)}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(monetary_currency)}">{_e(payable)}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
{lines_xml}
</Invoice>
"""

	meta = {
		"invoice": invoice.name,
		"customer": invoice.customer,
		"currency": currency,
		"line_count": len(resolution["lines"]),
		"net_total": net_total,
		"tax_total": total_tax_amount,
		"grand_total": payable,
		"tax_rates_used": [t["rate"] for t in resolution["tax_subtotals"]],
	}
	return xml, meta


# ---------------------------------------------------------------------------
# whitelisted API for the "Super PDP XML Configuration" page
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_mapping_table(template_name=None):
	return get_mapping_rows(template_name)


@frappe.whitelist()
def preview_invoice_mapping(invoice_name, template_name=None):
	invoice = frappe.get_doc("Sales Invoice", invoice_name)
	frappe.has_permission("Sales Invoice", doc=invoice_name, throw=True)
	return resolve_all(invoice, template_name)


@frappe.whitelist()
def preview_invoice_xml(invoice_name, template_name=None):
	invoice = frappe.get_doc("Sales Invoice", invoice_name)
	frappe.has_permission("Sales Invoice", doc=invoice_name, throw=True)
	try:
		xml, meta = render_invoice_xml(invoice, template_name)
		return {"ok": True, "xml": xml, "meta": meta}
	except UBLBuildError as exc:
		return {"ok": False, "error": str(exc)}
