# -*- coding: utf-8 -*-
"""
SuperPDP core client.

This module is a faithful Python port of the shared logic in the original
`config.js` test helper (endpoint + getSellerToken/getBuyerToken via
OAuth2 client_credentials). It exists because Frappe's backend runs
Python, not Node.js - so "reusing" the existing SuperPDP scripts inside
ERPNext means porting their exact request shape (same URL, same headers,
same params, same flow) rather than re-inventing it.

Nothing here ever returns a client secret to the caller. Secrets are only
read from the encrypted "Super PDP Settings" single doctype and used to
build the outgoing request - they are never included in any response
that is sent back to the browser.
"""

import frappe
import requests

DEFAULT_ENDPOINT = "https://api.superpdp.tech"

REQUEST_TIMEOUT = 30


class SuperPDPError(Exception):
	"""Raised when a SuperPDP call cannot be completed."""

	def __init__(self, message, http_status=None):
		super().__init__(message)
		self.http_status = http_status


def get_settings():
	return frappe.get_single("Super PDP Settings")


def get_endpoint():
	settings = get_settings()
	endpoint = (settings.get("superpdp_endpoint") or DEFAULT_ENDPOINT).strip()
	return endpoint.rstrip("/")


def get_seller_credentials():
	settings = get_settings()
	client_id = settings.get("burgerqueen_client_id")
	client_secret = settings.get_password("burgerqueen_client_secret", raise_exception=False)
	return client_id, client_secret


def get_buyer_credentials():
	settings = get_settings()
	client_id = settings.get("tricatel_client_id")
	client_secret = settings.get_password("tricatel_client_secret", raise_exception=False)
	return client_id, client_secret


def request_token(client_id, client_secret):
	"""Mirrors config.js `getToken()`.

	Returns a tuple: (ok, http_status, body_text, data_dict_or_None, error_message)
	"""
	if not client_id or not client_secret:
		return (
			False,
			None,
			None,
			None,
			"Missing client_id/client_secret. Configure them in Super PDP Settings.",
		)

	endpoint = get_endpoint()

	try:
		response = requests.post(
			f"{endpoint}/oauth2/token",
			headers={"Content-Type": "application/x-www-form-urlencoded"},
			data={
				"grant_type": "client_credentials",
				"client_id": client_id,
				"client_secret": client_secret,
			},
			timeout=REQUEST_TIMEOUT,
		)
	except requests.RequestException as exc:
		return False, None, None, None, str(exc)

	body_text = response.text

	if not response.ok:
		return False, response.status_code, body_text, None, f"OAuth {response.status_code}: {body_text}"

	try:
		data = response.json()
	except ValueError:
		return False, response.status_code, body_text, None, "Invalid JSON in token response"

	return True, response.status_code, body_text, data, None


def get_seller_token():
	"""Mirrors config.js `getSellerToken()`. Raises SuperPDPError on failure."""
	client_id, client_secret = get_seller_credentials()
	ok, status, _body, data, err = request_token(client_id, client_secret)
	if not ok:
		raise SuperPDPError(err, status)
	return data.get("access_token")


def get_buyer_token():
	"""Mirrors config.js `getBuyerToken()`. Raises SuperPDPError on failure."""
	client_id, client_secret = get_buyer_credentials()
	ok, status, _body, data, err = request_token(client_id, client_secret)
	if not ok:
		raise SuperPDPError(err, status)
	return data.get("access_token")


def do_request(method, path, headers=None, **kwargs):
	"""Generic helper: performs a request against the SuperPDP endpoint and
	always returns a normalised tuple instead of raising, so calling code
	can build a clean "ok / http_status / response / error" result for the
	UI, matching what the original scripts print to the console."""
	endpoint = get_endpoint()
	url = path if path.startswith("http") else f"{endpoint}{path}"
	try:
		response = requests.request(method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs)
	except requests.RequestException as exc:
		return False, None, None, str(exc)

	text = response.text
	if not response.ok:
		return False, response.status_code, text, f"HTTP {response.status_code}: {text}"
	return True, response.status_code, text, None
