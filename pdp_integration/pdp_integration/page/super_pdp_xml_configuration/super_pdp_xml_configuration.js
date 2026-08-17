// Copyright (c) 2026, Your Organization
// For license information, please see license.txt

frappe.pages["super-pdp-xml-configuration"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("SuperPDP XML Configuration"),
		single_column: true,
	});

	new SuperPDPXMLConfigPage(page);
};

const STATUS_BADGE = {
	Mapped: { color: "green", icon: "✓" },
	Computed: { color: "blue", icon: "⚙" },
	Static: { color: "grey", icon: "•" },
	"Missing Required": { color: "red", icon: "✗" },
	"Optional Unmapped": { color: "orange", icon: "⚠" },
	Invalid: { color: "red", icon: "✗" },
};

class SuperPDPXMLConfigPage {
	constructor(page) {
		this.page = page;
		this.selected_invoice = null;

		this.page.add_menu_item(__("Open Field Mapping List"), () => {
			frappe.set_route("List", "Super PDP XML Field Mapping");
		});
		this.page.add_menu_item(__("Open XML Template"), () => {
			frappe.set_route("List", "Super PDP XML Template");
		});
		this.page.add_menu_item(__("Reset Mapping to Defaults"), () => this.reset_mapping());

		this.setup_selectors();
		this.build_layout();
	}

	setup_selectors() {
		this.page.add_field({
			fieldtype: "Link",
			fieldname: "company",
			label: __("Company"),
			options: "Company",
			change: () => this.on_filters_changed(),
		});

		this.page.add_field({
			fieldtype: "Link",
			fieldname: "customer",
			label: __("Customer"),
			options: "Customer",
			change: () => this.on_filters_changed(),
		});

		this.page.add_field({
			fieldtype: "Link",
			fieldname: "sales_invoice",
			label: __("Sales Invoice"),
			options: "Sales Invoice",
			get_query: () => {
				const filters = { docstatus: ["!=", 2] };
				const company = this.page.fields_dict.company.get_value();
				const customer = this.page.fields_dict.customer.get_value();
				if (company) filters.company = company;
				if (customer) filters.customer = customer;
				return { filters };
			},
			change: () => {
				const inv = this.page.fields_dict.sales_invoice.get_value();
				if (inv) this.load_invoice(inv);
			},
		});
	}

	on_filters_changed() {
		this.page.fields_dict.sales_invoice.set_value("");
		this.selected_invoice = null;
		this.render_empty_state();
	}

	build_layout() {
		this.$body = $(`
			<div class="superpdp-xml-config">
				<div class="pdp-empty-state text-muted" style="padding: 40px 0; text-align:center;">
					${__("Select a Sales Invoice above to see exactly what will be sent to SuperPDP.")}
				</div>
				<div class="pdp-content" style="display:none;">
					<div class="pdp-summary-banner" style="margin-bottom: 14px;"></div>
					<div class="pdp-validation-report" style="margin-bottom: 14px;"></div>

					<h5>${__("Invoice-level fields")}</h5>
					<table class="table table-bordered table-sm pdp-mapping-table">
						<thead>
							<tr>
								<th>${__("XML Field")}</th>
								<th>${__("ERPNext Source")}</th>
								<th>${__("Transformation")}</th>
								<th>${__("Live Value")}</th>
								<th>${__("Status")}</th>
							</tr>
						</thead>
						<tbody class="pdp-invoice-fields"></tbody>
					</table>

					<h5>${__("Invoice Lines")} <span class="pdp-line-count text-muted small"></span></h5>
					<div class="pdp-lines"></div>

					<h5>${__("Tax Subtotals")} <span class="pdp-subtotal-count text-muted small"></span></h5>
					<div class="pdp-subtotals"></div>
				</div>
			</div>
		`).appendTo(this.page.body);

		this.page.set_primary_action(__("Preview XML"), () => this.preview_xml(), "code");
		this.page.set_secondary_action(__("Refresh"), () => {
			if (this.selected_invoice) this.load_invoice(this.selected_invoice);
		});
	}

	render_empty_state() {
		this.$body.find(".pdp-empty-state").show();
		this.$body.find(".pdp-content").hide();
	}

	load_invoice(invoice_name) {
		this.selected_invoice = invoice_name;
		this.$body.find(".pdp-empty-state").hide();
		this.$body.find(".pdp-content").show();
		this.$body.find(".pdp-summary-banner").html(
			`<i class="fa fa-spinner fa-spin"></i> ${__("Loading real ERPNext data for {0}...", [invoice_name])}`
		);

		frappe.call({
			method: "pdp_integration.xml_mapper.preview_invoice_mapping",
			args: { invoice_name },
		}).then((r) => {
			this.render_resolution(r.message);
		});
	}

	render_resolution(res) {
		this.last_resolution = res;

		const can_send = res.can_send;
		this.$body.find(".pdp-summary-banner").html(
			`<div class="indicator ${can_send ? "green" : "red"}">
				${can_send ? __("Ready to send - every required field is mapped") : __("Cannot send - required fields are missing")}
			</div>`
		);

		const $report = this.$body.find(".pdp-validation-report");
		if (res.blocking_errors.length) {
			$report.html(
				`<div class="pdp-validation-errors" style="background: var(--control-bg,#fff5f5); border-radius: 6px; padding: 10px;">
					<strong>${__("Validation report")}</strong>
					<ul style="margin:6px 0 0 18px;">
						${res.blocking_errors.map((e) => `<li>✗ ${frappe.utils.escape_html(e)}</li>`).join("")}
					</ul>
				</div>`
			);
		} else {
			$report.html("");
		}

		this.render_field_table(this.$body.find(".pdp-invoice-fields"), res.invoice_fields);

		this.$body.find(".pdp-line-count").text(`(${res.lines.length})`);
		const $lines = this.$body.find(".pdp-lines").empty();
		res.lines.forEach((line, idx) => {
			const $wrap = $(`
				<div class="pdp-line-block" style="margin-bottom: 10px;">
					<div class="text-muted small" style="margin-bottom:4px;">
						${__("Line {0}", [idx + 1])} - <strong>${frappe.utils.escape_html(line.item_name || line.item_code || "")}</strong>
					</div>
					<table class="table table-bordered table-sm pdp-mapping-table"></table>
				</div>
			`);
			this.render_field_table($wrap.find("table"), line.fields, true);
			$lines.append($wrap);
		});

		this.$body.find(".pdp-subtotal-count").text(`(${res.tax_subtotals.length})`);
		const $subtotals = this.$body.find(".pdp-subtotals").empty();
		res.tax_subtotals.forEach((t) => {
			const $wrap = $(`
				<div class="pdp-subtotal-block" style="margin-bottom: 10px;">
					<div class="text-muted small" style="margin-bottom:4px;">${__("VAT rate")}: <strong>${t.rate}%</strong></div>
					<table class="table table-bordered table-sm pdp-mapping-table"></table>
				</div>
			`);
			this.render_field_table($wrap.find("table"), t.fields, true);
			$subtotals.append($wrap);
		});
	}

	render_field_table($tbody_container, fields, with_header) {
		const rows = fields
			.map((f) => {
				const badge = STATUS_BADGE[f.status] || { color: "grey", icon: "?" };
				const source = f.source || (f.is_attribute ? `@${f.attribute_name}` : "-");
				const value = f.final_value === null || f.final_value === undefined ? "" : String(f.final_value);
				return `
					<tr>
						<td><code>${frappe.utils.escape_html(f.xml_path)}</code></td>
						<td>${frappe.utils.escape_html(source || "-")}</td>
						<td class="text-muted small">${frappe.utils.escape_html(f.transformation || "None")}</td>
						<td>${frappe.utils.escape_html(value)}</td>
						<td><span class="indicator ${badge.color}">${badge.icon} ${frappe.utils.escape_html(f.status)}</span></td>
					</tr>
				`;
			})
			.join("");

		if ($tbody_container.is("tbody")) {
			$tbody_container.html(rows);
		} else {
			// building a fresh <table> for line/subtotal blocks
			$tbody_container.html(`
				<thead>
					<tr>
						<th>${__("XML Field")}</th>
						<th>${__("ERPNext Source")}</th>
						<th>${__("Transformation")}</th>
						<th>${__("Live Value")}</th>
						<th>${__("Status")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			`);
		}
	}

	preview_xml() {
		if (!this.selected_invoice) {
			frappe.msgprint(__("Select a Sales Invoice first."));
			return;
		}

		frappe.call({
			method: "pdp_integration.xml_mapper.preview_invoice_xml",
			args: { invoice_name: this.selected_invoice },
		}).then((r) => {
			const result = r.message;
			if (!result.ok) {
				frappe.msgprint({
					title: __("Cannot Build XML"),
					indicator: "red",
					message: `<pre style="white-space:pre-wrap;">${frappe.utils.escape_html(result.error)}</pre>`,
				});
				return;
			}

			const d = new frappe.ui.Dialog({
				title: __("XML Preview: {0}", [this.selected_invoice]),
				size: "large",
				fields: [
					{
						fieldtype: "Code",
						fieldname: "xml_preview",
						options: "XML",
						label: __("Generated XML"),
						read_only: 1,
					},
				],
				primary_action_label: __("Send to SuperPDP"),
				primary_action: () => {
					d.hide();
					this.send_to_superpdp();
				},
			});
			d.set_value("xml_preview", result.xml);
			d.show();
		});
	}

	send_to_superpdp() {
		frappe.confirm(
			__("This sends the real invoice data shown above to SuperPDP (POST /v1.beta/invoices). Continue?"),
			() => {
				frappe.call({
					method: "pdp_integration.invoices.send_invoice_to_superpdp",
					args: { invoice_doctype: "Sales Invoice", invoice_name: this.selected_invoice },
				}).then((r) => {
					const result = r.message;
					const ok = result.summary && result.summary.overall === "Success";
					frappe.show_alert({
						message: ok
							? __("Sent to SuperPDP - invoice id {0}", [result.summary.superpdp_invoice_id || ""])
							: __("Send failed - see Super PDP Invoice Log for details"),
						indicator: ok ? "green" : "red",
					});
				});
			}
		);
	}

	reset_mapping() {
		frappe.confirm(
			__("This discards any local edits to the default XML field mapping and reseeds it from the app's shipped defaults. Continue?"),
			() => {
				frappe.call({ method: "pdp_integration.xml_seed.reset_default_mapping" }).then(() => {
					frappe.show_alert({ message: __("Mapping reset to defaults"), indicator: "green" });
					if (this.selected_invoice) this.load_invoice(this.selected_invoice);
				});
			}
		);
	}
}
