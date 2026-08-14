# -*- coding: utf-8 -*-
import frappe
from frappe.model.document import Document


class SuperPDPSettings(Document):
	def validate(self):
		if self.superpdp_endpoint:
			self.superpdp_endpoint = self.superpdp_endpoint.strip().rstrip("/")
