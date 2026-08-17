# -*- coding: utf-8 -*-
import frappe
from frappe.model.document import Document

from pdp_integration.xml_template import parse_template_json, XMLTemplateParseError


class SuperPDPXMLTemplate(Document):
	def validate(self):
		try:
			self.parsed_structure = parse_template_json(self.raw_xml)
		except XMLTemplateParseError as exc:
			frappe.throw(str(exc))

		if self.is_default:
			frappe.db.set_value(
				self.doctype, {"is_default": 1, "name": ["!=", self.name]}, "is_default", 0
			)
