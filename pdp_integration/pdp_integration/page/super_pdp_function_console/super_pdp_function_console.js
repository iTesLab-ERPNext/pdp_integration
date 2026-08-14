// Copyright (c) 2026, Your Organization
// For license information, please see license.txt

frappe.pages["super-pdp-function-console"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("SuperPDP Function Console"),
		single_column: true,
	});

	new SuperPDPFunctionConsole(page);
};

class SuperPDPFunctionConsole {
	constructor(page) {
		this.page = page;
		this.rows = {};
		this.page.set_primary_action(__("Run All (Recommended Order)"), () => this.run_all(), "play");
		this.page.add_menu_item(__("Open Settings"), () => frappe.set_route("Form", "Super PDP Settings"));
		this.page.add_menu_item(__("Open Invoice Interface"), () => frappe.set_route("super-pdp-invoices"));

		this.build_layout();
		this.load_status();
		this.load_registry();
	}

	build_layout() {
		this.$body = $(`
			<div class="superpdp-console">
				<div class="superpdp-settings-banner" style="margin-bottom: 12px;"></div>
				<table class="table table-bordered superpdp-fn-table">
					<thead>
						<tr>
							<th style="width: 22%">${__("Function")}</th>
							<th style="width: 16%">${__("JS File")}</th>
							<th style="width: 10%">${__("Role")}</th>
							<th style="width: 12%">${__("Status")}</th>
							<th style="width: 10%">${__("HTTP")}</th>
							<th style="width: 12%">${__("Test")}</th>
							<th>${__("Details")}</th>
						</tr>
					</thead>
					<tbody></tbody>
				</table>
			</div>
		`).appendTo(this.page.body);

		this.$banner = this.$body.find(".superpdp-settings-banner");
		this.$tbody = this.$body.find("tbody");
	}

	load_status() {
		frappe.call({ method: "pdp_integration.superpdp_functions.get_settings_status" }).then((r) => {
			const s = r.message || {};
			if (s.seller_configured && s.buyer_configured) {
				this.$banner.html(
					`<div class="indicator green">${__("SuperPDP credentials configured")}</div> <span class="text-muted small">${frappe.utils.escape_html(s.endpoint || "")}</span>`
				);
			} else {
				this.$banner.html(
					`<div class="indicator orange">${__("SuperPDP credentials incomplete")}</div> ` +
						`<a href="/app/super-pdp-settings">${__("Configure Super PDP Settings")}</a>`
				);
			}
		});
	}

	load_registry() {
		frappe.call({ method: "pdp_integration.superpdp_functions.get_function_registry" }).then((r) => {
			(r.message || []).forEach((fn) => this.add_row(fn));
		});
	}

	add_row(fn) {
		const $row = $(`
			<tr data-fn="${fn.id}">
				<td>
					<strong>${frappe.utils.escape_html(fn.label)}</strong>
					<div class="text-muted small">${frappe.utils.escape_html(fn.description || "")}</div>
				</td>
				<td><code>${frappe.utils.escape_html(fn.file)}</code></td>
				<td>${frappe.utils.escape_html(fn.role)}</td>
				<td class="fn-status"><span class="indicator grey">${__("Not run")}</span></td>
				<td class="fn-http text-muted">-</td>
				<td><button class="btn btn-xs btn-primary btn-run">${__("Run Test")}</button></td>
				<td class="fn-details text-muted small">-</td>
			</tr>
		`);

		$row.find(".btn-run").on("click", () => this.run_one(fn.id));
		this.$tbody.append($row);
		this.rows[fn.id] = $row;
	}

	set_row_state($row, state) {
		const status_map = {
			running: { color: "blue", label: __("Running...") },
			success: { color: "green", label: __("Success") },
			failed: { color: "red", label: __("Failed") },
		};
		const s = status_map[state.status];
		$row.find(".fn-status").html(`<span class="indicator ${s.color}">${s.label}</span>`);
		$row.find(".fn-http").text(state.http_status || "-");

		if (state.status === "running") {
			$row.find(".fn-details").html(`<i class="fa fa-spinner fa-spin"></i>`);
			return;
		}

		const detail_text = state.ok
			? json_preview(state.response)
			: state.error || __("Unknown error");

		const $details = $row.find(".fn-details");
		$details.empty();
		const $toggle = $(`<a href="#">${__("View")}</a>`);
		const $pre = $(`<pre class="superpdp-pre" style="display:none; max-width: 480px; white-space: pre-wrap;"></pre>`).text(
			detail_text
		);
		$toggle.on("click", (e) => {
			e.preventDefault();
			$pre.toggle();
		});
		$details.append($toggle).append($pre);
	}

	run_one(fn_id) {
		const $row = this.rows[fn_id];
		this.set_row_state($row, { status: "running" });

		return frappe.call({ method: "pdp_integration.superpdp_functions.run_function", args: { function_id: fn_id } }).then((r) => {
			const result = r.message || {};
			this.set_row_state($row, {
				status: result.ok ? "success" : "failed",
				http_status: result.http_status,
				ok: result.ok,
				response: result.response,
				error: result.error,
			});
			return result;
		});
	}

	async run_all() {
		const order = [
			"01_seller_token",
			"02_buyer_token",
			"03_seller_company",
			"04_generate_invoice",
			"05_validate_invoice",
			"06_list_buyer_invoices",
			"07_send_invoice",
			"08_check_received_invoice",
			"09_check_invoice_status",
			"10_send_paid_event",
		];
		for (const fn_id of order) {
			// eslint-disable-next-line no-await-in-loop
			await this.run_one(fn_id);
		}
		frappe.show_alert({ message: __("SuperPDP function sequence complete"), indicator: "blue" });
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
