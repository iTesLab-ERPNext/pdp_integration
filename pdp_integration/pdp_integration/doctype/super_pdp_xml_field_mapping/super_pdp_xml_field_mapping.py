# -*- coding: utf-8 -*-
import frappe
from frappe.model.document import Document


class SuperPDPXMLFieldMapping(Document):
	def validate(self):
		if self.is_attribute and not self.attribute_name:
			frappe.throw("Attribute Name is required when 'Is XML Attribute' is checked.")

		if self.transformation == "Static Value" and not self.static_value:
			frappe.throw("Static Value is required when Transformation is 'Static Value'.")

		if self.transformation not in ("Static Value", "Computed by Engine"):
			if bool(self.erpnext_doctype) != bool(self.erpnext_field):
				frappe.throw("ERPNext Doctype and ERPNext Field must both be set, or both left blank.")

		if not self.section:
			self.section = (self.xml_path or "").split("/")[0].split("@")[0]
