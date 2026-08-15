# -*- coding: utf-8 -*-
"""
Builds a UBL 2.1 (EN 16931 / BIS Billing 3.0 shape - same shape as the
SuperPDP sandbox `test_invoice.xml`) invoice document from a *real*
ERPNext Sales Invoice: real customer, real line items, real quantities,
real prices, real taxes, real totals. No product/amount data is
hardcoded or copied from the SuperPDP sample invoice - only the fixed,
structural parts of the UBL document (namespaces, CustomizationID,
ProfileID) are constant, exactly as they are constant in any UBL
invoice regardless of its content.

Routing identifiers (SIRET) that ERPNext has no native field for are
read from "Super PDP Settings" (seller) and, for the buyer, from a
`custom_siret` field on the Customer if present, else a configured
default. If neither is available the builder raises a clear,
actionable error instead of silently sending a fake/placeholder id.
"""

import json
from xml.sax.saxutils import escape as xml_escape

import frappe
from frappe.utils import flt, cint

UBL_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"

# Best-effort ERPNext UOM -> UN/ECE Recommendation 20 unit code mapping.
# C62 ("one" / piece) is the safe generic fallback used by the sample invoice.
UOM_CODE_MAP = {
	"nos": "C62",
	"unit": "C62",
	"each": "C62",
	"kg": "KGM",
	"kilogram": "KGM",
	"gram": "GRM",
	"g": "GRM",
	"litre": "LTR",
	"liter": "LTR",
	"l": "LTR",
	"metre": "MTR",
	"meter": "MTR",
	"m": "MTR",
	"hour": "HUR",
	"hr": "HUR",
	"day": "DAY",
	"box": "BX",
	"pair": "PR",
}


class UBLBuildError(frappe.ValidationError):
	pass


def _e(value):
	return xml_escape("" if value is None else str(value))


def _money(value):
	return f"{flt(value):.2f}"


def _country_code(country_name):
	if not country_name:
		return "FR"
	code = frappe.db.get_value("Country", country_name, "code")
	return (code or "FR").upper()


def _uom_code(uom):
	if not uom:
		return "C62"
	return UOM_CODE_MAP.get(uom.strip().lower(), "C62")


def _siren_from_siret(siret):
	siret = (siret or "").replace(" ", "")
	if len(siret) == 14:
		return siret[:9]
	return siret


def _get_settings():
	return frappe.get_single("Super PDP Settings")


def _seller_party(company_doc, settings):
	siret = (settings.get("seller_siret") or "").strip()
	if not siret:
		frappe.throw(
			"Seller SIRET is not configured. Set it in Super PDP Settings before sending a real invoice.",
			UBLBuildError,
		)
	vat_number = (company_doc.get("tax_id") or "").strip()
	if not vat_number:
		frappe.throw(
			f"Company {company_doc.name} has no Tax ID (VAT number) set. Set it on the Company record.",
			UBLBuildError,
		)
	return {
		"endpoint_id": siret,
		"country_code": _country_code(company_doc.get("country")),
		"vat_number": vat_number,
		"registration_name": company_doc.get("company_name") or company_doc.name,
		"legal_company_id": _siren_from_siret(siret),
	}


def _buyer_party(customer_doc, settings):
	siret = (customer_doc.get("custom_siret") or settings.get("default_buyer_siret") or "").strip()
	if not siret:
		frappe.throw(
			f"No SIRET available for customer {customer_doc.name}. Set a 'custom_siret' field on the "
			"Customer or configure a Default Buyer SIRET in Super PDP Settings.",
			UBLBuildError,
		)
	vat_number = (customer_doc.get("tax_id") or "").strip()
	return {
		"endpoint_id": siret,
		"country_code": _country_code(customer_doc.get("territory")) or "FR",
		"vat_number": vat_number,
		"registration_name": customer_doc.get("customer_name") or customer_doc.name,
		"legal_company_id": _siren_from_siret(siret),
	}


def _item_tax_rate_percent(item, invoice):
	"""Best-effort per-line VAT rate: prefer the item's own item_tax_rate
	breakdown (ERPNext computes and stores this JSON on save/submit),
	else fall back to the invoice's overall effective tax rate."""
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


def _party_xml(tag, party):
	tax_scheme = (
		f'<cac:PartyTaxScheme xmlns:cac="{CAC_NS}">'
		f'<cbc:CompanyID xmlns:cbc="{CBC_NS}">{_e(party["vat_number"])}</cbc:CompanyID>'
		f'<cac:TaxScheme xmlns:cac="{CAC_NS}"><cbc:ID xmlns:cbc="{CBC_NS}">VAT</cbc:ID></cac:TaxScheme>'
		f"</cac:PartyTaxScheme>"
		if party.get("vat_number")
		else ""
	)
	return f"""
  <cac:{tag} xmlns:cac="{CAC_NS}">
    <cac:Party xmlns:cac="{CAC_NS}">
      <cbc:EndpointID xmlns:cbc="{CBC_NS}" schemeID="0225">{_e(party['endpoint_id'])}</cbc:EndpointID>
      <cac:PostalAddress xmlns:cac="{CAC_NS}">
        <cac:Country xmlns:cac="{CAC_NS}">
          <cbc:IdentificationCode xmlns:cbc="{CBC_NS}">{_e(party['country_code'])}</cbc:IdentificationCode>
        </cac:Country>
      </cac:PostalAddress>
      {tax_scheme}
      <cac:PartyLegalEntity xmlns:cac="{CAC_NS}">
        <cbc:RegistrationName xmlns:cbc="{CBC_NS}">{_e(party['registration_name'])}</cbc:RegistrationName>
        <cbc:CompanyID xmlns:cbc="{CBC_NS}" schemeID="0002">{_e(party['legal_company_id'])}</cbc:CompanyID>
      </cac:PartyLegalEntity>
    </cac:Party>
  </cac:{tag}>""".strip("\n")


def _invoice_line_xml(idx, item, rate_percent):
	category = "Z" if rate_percent == 0 else "S"
	description_text = frappe.utils.strip_html(item.get("description") or "").strip()
	item_name = item.get("item_name") or item.get("item_code") or ""
	# Only emit a separate <Description> when it adds information beyond the name.
	if description_text and description_text.lower() == item_name.strip().lower():
		description_text = ""
	description_xml = (
		f'<cbc:Description xmlns:cbc="{CBC_NS}">{_e(description_text[:1000])}</cbc:Description>'
		if description_text
		else ""
	)
	return f"""
  <cac:InvoiceLine xmlns:cac="{CAC_NS}">
    <cbc:ID xmlns:cbc="{CBC_NS}">{idx:03d}</cbc:ID>
    <cbc:InvoicedQuantity xmlns:cbc="{CBC_NS}" unitCode="{_e(_uom_code(item.get('uom')))}">{flt(item.get('qty')):.3f}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(item['currency'])}">{_money(item.get('net_amount') or item.get('amount'))}</cbc:LineExtensionAmount>
    <cac:Item xmlns:cac="{CAC_NS}">
      {description_xml}
      <cbc:Name xmlns:cbc="{CBC_NS}">{_e(item.get('item_name') or item.get('item_code'))}</cbc:Name>
      <cac:ClassifiedTaxCategory xmlns:cac="{CAC_NS}">
        <cbc:ID xmlns:cbc="{CBC_NS}">{category}</cbc:ID>
        <cbc:Percent xmlns:cbc="{CBC_NS}">{flt(rate_percent):.1f}</cbc:Percent>
        <cac:TaxScheme xmlns:cac="{CAC_NS}"><cbc:ID xmlns:cbc="{CBC_NS}">VAT</cbc:ID></cac:TaxScheme>
      </cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price xmlns:cac="{CAC_NS}">
      <cbc:PriceAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(item['currency'])}">{_money(item.get('rate'))}</cbc:PriceAmount>
    </cac:Price>
  </cac:InvoiceLine>""".strip("\n")


def _tax_subtotal_xml(rate_percent, taxable_amount, tax_amount, currency):
	category = "Z" if rate_percent == 0 else "S"
	return f"""
    <cac:TaxSubtotal xmlns:cac="{CAC_NS}">
      <cbc:TaxableAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(currency)}">{_money(taxable_amount)}</cbc:TaxableAmount>
      <cbc:TaxAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(currency)}">{_money(tax_amount)}</cbc:TaxAmount>
      <cac:TaxCategory xmlns:cac="{CAC_NS}">
        <cbc:ID xmlns:cbc="{CBC_NS}">{category}</cbc:ID>
        <cbc:Percent xmlns:cbc="{CBC_NS}">{flt(rate_percent):.1f}</cbc:Percent>
        <cac:TaxScheme xmlns:cac="{CAC_NS}"><cbc:ID xmlns:cbc="{CBC_NS}">VAT</cbc:ID></cac:TaxScheme>
      </cac:TaxCategory>
    </cac:TaxSubtotal>""".strip("\n")


def build_invoice_xml(invoice):
	"""invoice: a loaded ERPNext Sales Invoice document.

	Returns (xml_string, meta_dict) where meta_dict is a short, safe
	summary (line count, totals, currency) suitable for showing in the
	UI without dumping the full XML.
	"""
	if invoice.doctype != "Sales Invoice":
		frappe.throw("A real UBL invoice can only be built from a Sales Invoice (seller role).", UBLBuildError)

	if not invoice.get("items"):
		frappe.throw(f"{invoice.name} has no line items.", UBLBuildError)

	settings = _get_settings()
	company_doc = frappe.get_cached_doc("Company", invoice.company)
	customer_doc = frappe.get_cached_doc("Customer", invoice.customer)

	seller = _seller_party(company_doc, settings)
	buyer = _buyer_party(customer_doc, settings)

	currency = invoice.currency or company_doc.get("default_currency") or "EUR"

	# Build invoice lines + group taxable amounts by VAT rate (matches the
	# structure of the SuperPDP sample: one TaxSubtotal per distinct rate).
	lines_xml = []
	rate_groups = {}  # rate_percent -> {"taxable": x, "tax": y}

	for idx, item in enumerate(invoice.items, start=1):
		item = item.as_dict()
		item["currency"] = currency
		rate_percent = flt(_item_tax_rate_percent(item, invoice))
		lines_xml.append(_invoice_line_xml(idx, item, rate_percent))

		taxable = flt(item.get("net_amount") or item.get("amount"))
		bucket = rate_groups.setdefault(rate_percent, {"taxable": 0.0, "tax": 0.0})
		bucket["taxable"] += taxable
		bucket["tax"] += taxable * rate_percent / 100

	tax_subtotals_xml = []
	total_tax_amount = 0.0
	for rate_percent in sorted(rate_groups.keys()):
		bucket = rate_groups[rate_percent]
		tax_subtotals_xml.append(_tax_subtotal_xml(rate_percent, bucket["taxable"], bucket["tax"], currency))
		total_tax_amount += bucket["tax"]

	# Reconcile against ERPNext's own computed tax total when available -
	# ERPNext's rounding/tax engine is the source of truth for the total.
	if invoice.get("total_taxes_and_charges") is not None:
		total_tax_amount = flt(invoice.get("total_taxes_and_charges"))

	invoice_type_code = "381" if cint(invoice.get("is_return")) else "380"
	issue_date = invoice.get("posting_date")
	due_date = invoice.get("due_date") or issue_date

	notes_xml = ""
	terms = (invoice.get("tc_name") and invoice.get("terms")) or ""
	if terms:
		clean_terms = frappe.utils.strip_html(terms)[:500]
		if clean_terms:
			notes_xml = f'\n  <cbc:Note xmlns:cbc="{CBC_NS}">{_e(clean_terms)}</cbc:Note>'

	net_total = flt(invoice.get("net_total"))
	grand_total = flt(invoice.get("grand_total"))

	xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="{UBL_NS}">
  <cbc:CustomizationID xmlns:cbc="{CBC_NS}">urn:cen.eu:en16931:2017</cbc:CustomizationID>
  <cbc:ProfileID xmlns:cbc="{CBC_NS}">M1</cbc:ProfileID>
  <cbc:ID xmlns:cbc="{CBC_NS}">{_e(invoice.name)}</cbc:ID>
  <cbc:IssueDate xmlns:cbc="{CBC_NS}">{_e(issue_date)}</cbc:IssueDate>
  <cbc:DueDate xmlns:cbc="{CBC_NS}">{_e(due_date)}</cbc:DueDate>
  <cbc:InvoiceTypeCode xmlns:cbc="{CBC_NS}">{invoice_type_code}</cbc:InvoiceTypeCode>{notes_xml}
  <cbc:DocumentCurrencyCode xmlns:cbc="{CBC_NS}">{_e(currency)}</cbc:DocumentCurrencyCode>
{_party_xml("AccountingSupplierParty", seller)}
{_party_xml("AccountingCustomerParty", buyer)}
  <cac:TaxTotal xmlns:cac="{CAC_NS}">
    <cbc:TaxAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(currency)}">{_money(total_tax_amount)}</cbc:TaxAmount>
{chr(10).join(tax_subtotals_xml)}
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal xmlns:cac="{CAC_NS}">
    <cbc:LineExtensionAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(currency)}">{_money(net_total)}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(currency)}">{_money(net_total)}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(currency)}">{_money(grand_total)}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount xmlns:cbc="{CBC_NS}" currencyID="{_e(currency)}">{_money(grand_total)}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
{chr(10).join(lines_xml)}
</Invoice>
"""

	meta = {
		"invoice": invoice.name,
		"customer": customer_doc.name,
		"currency": currency,
		"line_count": len(invoice.items),
		"net_total": net_total,
		"tax_total": total_tax_amount,
		"grand_total": grand_total,
		"tax_rates_used": sorted(rate_groups.keys()),
	}
	return xml, meta
