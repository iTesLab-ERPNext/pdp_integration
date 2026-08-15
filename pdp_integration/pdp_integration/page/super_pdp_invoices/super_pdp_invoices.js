// Copyright (c) 2026, Your Organization
// For license information, please see license.txt

frappe.pages["super-pdp-invoices"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("SuperPDP Invoices"),
		single_column: true,
	});

	new SuperPDPInvoicesPage(page);
};

class SuperPDPInvoicesPage {
	constructor(page) {
		this.page = page;
		this.invoice_doctype = "Sales Invoice";
		this.setup_controls();
		this.build_layout();
		this.load_invoices();
	}

	setup_controls() {
		this.page.add_field({
			fieldtype: "Select",
			fieldname: "invoice_doctype",
			label: __("Invoice Type"),
			options: ["Sales Invoice", "Purchase Invoice"],
			default: "Sales Invoice",
			change: () => {
				this.invoice_doctype = this.page.fields_dict.invoice_doctype.get_value();
				this.load_invoices();
			},
		});

		this.page.add_field({
			fieldtype: "Data",
			fieldname: "search",
			label: __("Search"),
			change: () => this.load_invoices(),
		});

		this.page.set_primary_action(__("Refresh"), () => this.load_invoices(), "refresh");
	}

	build_layout() {
		this.$body = $(`
			<div class="superpdp-invoices">
				<div class="superpdp-banner text-muted small" style="margin-bottom: 10px;"></div>
				<div class="superpdp-table-wrapper">
					<table class="table table-bordered superpdp-table">
						<thead>
							<tr>
								<th>${__("Invoice")}</th>
								<th>${__("Party")}</th>
								<th>${__("Date")}</th>
								<th>${__("Amount")}</th>
								<th>${__("Status")}</th>
								<th>${__("SuperPDP")}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
				</div>
			</div>
		`).appendTo(this.page.body);

		this.$banner = this.$body.find(".superpdp-banner");
		this.$tbody = this.$body.find("tbody");
	}

	load_invoices() {
		this.$tbody.html(
			`<tr><td colspan="6" class="text-muted"><i class="fa fa-spinner fa-spin"></i> ${__("Loading...")}</td></tr>`
		);

		const search = this.page.fields_dict.search.get_value();

		frappe.call({
			method: "pdp_integration.invoices.get_invoices",
			args: { invoice_doctype: this.invoice_doctype, search: search || undefined },
			callback: (r) => this.render_invoices(r.message),
		});
	}

	render_invoices(data) {
		if (!data) return;
		const { invoices, role } = data;

		this.$banner.text(
			__("Showing {0} invoices. Role detected: {1}. \"Test with SuperPDP\" runs the {1}-side SuperPDP sandbox pipeline for the matching invoice.", [
				this.invoice_doctype,
				role,
			])
		);

		if (!invoices || !invoices.length) {
			this.$tbody.html(`<tr><td colspan="6" class="text-muted">${__("No invoices found.")}</td></tr>`);
			return;
		}

		this.$tbody.empty();
		const can_send = this.invoice_doctype === "Sales Invoice";

		invoices.forEach((inv) => {
			const $row = $(`
				<tr>
					<td><a href="/app/${frappe.router.slug(this.invoice_doctype)}/${encodeURIComponent(inv.name)}" target="_blank">${frappe.utils.escape_html(inv.name)}</a></td>
					<td>${frappe.utils.escape_html(inv.party || "")}</td>
					<td>${frappe.datetime.str_to_user(inv.posting_date) || ""}</td>
					<td>${format_currency(inv.grand_total, inv.currency)}</td>
					<td><span class="indicator ${status_color(inv.status)}">${frappe.utils.escape_html(inv.status || "")}</span></td>
					<td>
						<button class="btn btn-xs btn-primary btn-test">${__("Test with SuperPDP")}</button>
						${can_send ? `<button class="btn btn-xs btn-success btn-send" style="margin-left: 4px;">${__("Send to SuperPDP")}</button>` : ""}
						<span class="superpdp-row-status text-muted small" style="margin-left: 6px;"></span>
					</td>
				</tr>
			`);

			$row.find(".btn-test").on("click", (e) => {
				this.test_invoice(inv, $row, $(e.currentTarget));
			});

			if (can_send) {
				$row.find(".btn-send").on("click", (e) => {
					this.send_invoice(inv, $row, $(e.currentTarget));
				});
			}

			this.$tbody.append($row);
		});
	}

	test_invoice(invoice, $row, $btn) {
		$btn.prop("disabled", true);
		const $status = $row.find(".superpdp-row-status");
		$status.html(`<i class="fa fa-spinner fa-spin"></i> ${__("Testing...")}`);

		frappe.call({
			method: "pdp_integration.invoices.test_invoice_with_superpdp",
			args: { invoice_doctype: this.invoice_doctype, invoice_name: invoice.name },
			callback: (r) => {
				$btn.prop("disabled", false);
				const result = r.message;
				if (!result) {
					$status.html(`<span class="indicator red">${__("No response")}</span>`);
					return;
				}
				const ok = result.summary && result.summary.overall === "Success";
				$status.html(
					`<span class="indicator ${ok ? "green" : "red"}">${ok ? __("Passed") : __("Failed")}</span>`
				);
				this.show_result_dialog(invoice, result);
			},
			error: () => {
				$btn.prop("disabled", false);
				$status.html(`<span class="indicator red">${__("Error")}</span>`);
			},
		});
	}

	send_invoice(invoice, $row, $btn) {
		frappe.confirm(
			__(
				"This builds a real UBL invoice from {0}'s own customer, line items, and totals, and sends it to SuperPDP (07_send_invoice.js - POST /v1.beta/invoices) as the seller. Continue?",
				[invoice.name]
			),
			() => this.do_send_invoice(invoice, $row, $btn)
		);
	}

	do_send_invoice(invoice, $row, $btn) {
		$btn.prop("disabled", true);
		const $status = $row.find(".superpdp-row-status");
		$status.html(`<i class="fa fa-spinner fa-spin"></i> ${__("Sending...")}`);

		frappe.call({
			method: "pdp_integration.invoices.send_invoice_to_superpdp",
			args: { invoice_doctype: this.invoice_doctype, invoice_name: invoice.name },
			callback: (r) => {
				$btn.prop("disabled", false);
				const result = r.message;
				if (!result) {
					$status.html(`<span class="indicator red">${__("No response")}</span>`);
					return;
				}
				const ok = result.summary && result.summary.overall === "Success";
				$status.html(
					`<span class="indicator ${ok ? "green" : "red"}">${ok ? __("Sent") : __("Failed")}</span>`
				);
				if (ok && result.summary.superpdp_invoice_id) {
					frappe.show_alert({
						message: __("Sent to SuperPDP - invoice id {0}", [result.summary.superpdp_invoice_id]),
						indicator: "green",
					});
				}
				this.show_result_dialog(invoice, result, { title: __("SuperPDP Send Result: {0}", [invoice.name]) });
			},
			error: () => {
				$btn.prop("disabled", false);
				$status.html(`<span class="indicator red">${__("Error")}</span>`);
			},
		});
	}

	show_result_dialog(invoice, result, opts) {
		const steps_html = (result.steps || [])
			.map((step) => {
				const color = step.ok ? "green" : "red";
				const body = step.ok
					? `<pre class="superpdp-pre">${frappe.utils.escape_html(json_preview(step.response))}</pre>`
					: `<div class="text-danger">${frappe.utils.escape_html(step.error || "Unknown error")}</div>`;
				return `
					<div class="superpdp-step" style="margin-bottom: 10px;">
						<div><span class="indicator ${color}">${frappe.utils.escape_html(step.label)}</span>
							<span class="text-muted small">HTTP ${step.http_status || "-"}</span></div>
						${body}
					</div>
				`;
			})
			.join("");

		const d = new frappe.ui.Dialog({
			title: (opts && opts.title) || __("SuperPDP Test Result: {0}", [invoice.name]),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "result_html",
					options: `
						<div class="superpdp-summary text-muted small" style="margin-bottom: 10px;">
							${frappe.utils.escape_html(result.summary && result.summary.note ? result.summary.note : "")}
							${
								result.summary && result.summary.superpdp_invoice_id
									? `<div><strong>${__("SuperPDP Invoice ID")}:</strong> ${frappe.utils.escape_html(result.summary.superpdp_invoice_id)}</div>`
									: ""
							}
						</div>
						${steps_html}
					`,
				},
			],
			primary_action_label: __("View Full Log"),
			primary_action: () => {
				d.hide();
				frappe.set_route("List", "Super PDP Invoice Log", {
					invoice_doctype: this.invoice_doctype,
					invoice: invoice.name,
				});
			},
		});
		d.show();
	}
}

function json_preview(value) {
	if (value === null || value === undefined) return "";
	if (typeof value === "string") return value;
	try {
		return JSON.stringify(value, null, 2);
	} catch (e) {
		return String(value);
	}
}

function status_color(status) {
	const map = {
		Paid: "green",
		Unpaid: "orange",
		Overdue: "red",
		Draft: "grey",
		Submitted: "blue",
		Cancelled: "red",
		"Return": "grey",
	};
	return map[status] || "grey";
}
