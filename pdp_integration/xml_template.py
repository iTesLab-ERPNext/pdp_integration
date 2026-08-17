# -*- coding: utf-8 -*-
"""
Parses a reference UBL/XML invoice into a generic, ordered field list:
one entry per leaf element or attribute, with its path, its top-level
section, and which "scope" it belongs to (Invoice / InvoiceLine /
TaxSubtotal / Note) so repeating elements are recognised structurally
instead of by hardcoding "InvoiceLine" and "TaxSubtotal" as special
cases in the parser itself - any XML template with repeated sibling
elements gets the same treatment.

This module only reads a template; it never touches ERPNext data. It
exists so:
  - "Super PDP XML Template" can store a raw XML sample and derive its
    field list automatically (used to seed "Super PDP XML Field
    Mapping" rows), and
  - a second XML version/template can be added later without changing
    any code - just save a new template document.
"""

import json
import xml.etree.ElementTree as ET

REPEATING_SCOPE_TAGS = ("InvoiceLine", "TaxSubtotal")


class XMLTemplateParseError(Exception):
	pass


def _local_name(tag):
	return tag.split("}", 1)[1] if "}" in tag else tag


def _infer_scope(path_parts):
	"""path_parts includes the root element name at index 0."""
	for tag in REPEATING_SCOPE_TAGS:
		if tag in path_parts[1:]:
			return tag
	if len(path_parts) == 2 and path_parts[1] == "Note":
		return "Note"
	return "Invoice"


def parse_template(raw_xml):
	"""Returns {"root": <root tag>, "fields": [ {path, element_path,
	is_attribute, attribute_name, sample_value, section, scope}, ... ]}

	`path` is relative to the root element (root itself excluded), e.g.
	"AccountingSupplierParty/Party/EndpointID" or, for an attribute,
	"AccountingSupplierParty/Party/EndpointID@schemeID". Duplicate paths
	that come from repeated sibling elements (multiple <InvoiceLine>,
	<TaxSubtotal>, <Note>) are collapsed to a single field entry - the
	repetition itself is captured via `scope`, not via distinct rows.
	"""
	try:
		root = ET.fromstring(raw_xml)
	except ET.ParseError as exc:
		raise XMLTemplateParseError(f"Could not parse XML: {exc}") from exc

	root_name = _local_name(root.tag)
	collected = []

	def walk(el, path_parts):
		tag = _local_name(el.tag)
		path_parts = path_parts + [tag]
		rel_path = "/".join(path_parts[1:])
		section = path_parts[1] if len(path_parts) > 1 else None
		scope = _infer_scope(path_parts)

		for attr_name, attr_val in el.attrib.items():
			if attr_name.startswith("{http://www.w3.org/2000/xmlns/}") or attr_name == "xmlns":
				continue
			local_attr = _local_name(attr_name)
			collected.append(
				{
					"path": f"{rel_path}@{local_attr}",
					"element_path": rel_path,
					"is_attribute": True,
					"attribute_name": local_attr,
					"sample_value": attr_val,
					"section": section,
					"scope": scope,
				}
			)

		children = list(el)
		if not children:
			text = (el.text or "").strip()
			collected.append(
				{
					"path": rel_path,
					"element_path": rel_path,
					"is_attribute": False,
					"attribute_name": None,
					"sample_value": text,
					"section": section,
					"scope": scope,
				}
			)
		else:
			for child in children:
				walk(child, path_parts)

	walk(root, [])

	# Collapse duplicates from repeated sibling elements (keep first occurrence).
	dedup = {}
	for field in collected:
		key = (field["path"], field["scope"])
		if key not in dedup:
			dedup[key] = field

	fields = list(dedup.values())
	fields.sort(key=lambda f: (f["scope"] != "Invoice", f["section"] or "", f["path"]))

	return {"root": root_name, "fields": fields}


def parse_template_json(raw_xml):
	"""Convenience wrapper returning the parsed structure as a JSON string
	(what "Super PDP XML Template.parsed_structure" stores)."""
	return json.dumps(parse_template(raw_xml), indent=2, ensure_ascii=False)
