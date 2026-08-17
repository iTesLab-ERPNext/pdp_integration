# -*- coding: utf-8 -*-
"""
Backward-compatible shim. The actual UBL generation now lives in
xml_mapper.py, driven by the "Super PDP XML Field Mapping" doctype so
an administrator can inspect, validate, and edit every ERPNext -> XML
field mapping before a real invoice is sent (see the "Super PDP XML
Configuration" page). This module is kept so existing imports
(`from pdp_integration.ubl_builder import build_invoice_xml`) keep
working unchanged.
"""

from pdp_integration.xml_mapper import render_invoice_xml as build_invoice_xml  # noqa: F401
from pdp_integration.xml_mapper import UBLBuildError  # noqa: F401
from pdp_integration.xml_mapper import siren_from_siret, country_code, uom_code  # noqa: F401
