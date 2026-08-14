// Copyright (c) 2026, Your Organization
// For license information, please see license.txt

frappe.ui.form.on("Super PDP Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Seller Connection"), () => test_connection(frm, "seller"));
		frm.add_custom_button(__("Test Buyer Connection"), () => test_connection(frm, "buyer"));

		frm.add_custom_button(__("Open Invoice Interface"), () => {
			frappe.set_route("super-pdp-invoices");
		});
		frm.add_custom_button(__("Open Function Console"), () => {
			frappe.set_route("super-pdp-function-console");
		});

		render_status(frm, null);
	},
});

function test_connection(frm, role) {
	const method =
		role === "seller"
			? "pdp_integration.superpdp_functions.run_seller_token"
			: "pdp_integration.superpdp_functions.run_buyer_token";

	render_status(frm, { loading: true, role });

	frappe.call({ method }).then((r) => {
		const result = r.message || {};
		render_status(frm, { loading: false, role, result });
		if (result.ok) {
			frappe.show_alert({ message: __("{0} connection OK", [role]), indicator: "green" });
		} else {
			frappe.show_alert({ message: __("{0} connection failed", [role]), indicator: "red" });
		}
	});
}

function render_status(frm, state) {
	const el = frm.fields_dict.connection_status_html.$wrapper;
	if (!state) {
		el.html(`<div class="text-muted">${__("Use the buttons above to test the connection.")}</div>`);
		return;
	}
	if (state.loading) {
		el.html(`<div class="text-muted"><i class="fa fa-spinner fa-spin"></i> ${__("Testing {0} connection...", [state.role])}</div>`);
		return;
	}
	const ok = state.result && state.result.ok;
	const color = ok ? "green" : "red";
	const label = ok ? __("Connected") : __("Failed");
	const detail = ok
		? __("HTTP {0}", [state.result.http_status])
		: frappe.utils.escape_html(state.result.error || "");
	el.html(
		`<div><span class="indicator ${color}">${frappe.utils.escape_html(state.role)}: ${label}</span> ` +
			`<span class="text-muted small">${detail}</span></div>`
	);
}
