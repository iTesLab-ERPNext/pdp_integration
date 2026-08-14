# -*- coding: utf-8 -*-
from frappe import _


def get_data():
	"""Legacy (pre-Workspace, Frappe < v13) module icon fallback. Modern
	sites use the "PDP Integration" Workspace instead
	(pdp_integration/pdp_integration/workspace/pdp_integration); this is
	only read by older desk versions that still build the sidebar from
	config/desktop.py."""
	return [
		{
			"module_name": "PDP Integration",
			"color": "#2e7d32",
			"icon": "octicon octicon-plug",
			"type": "module",
			"label": _("PDP Integration"),
		}
	]
