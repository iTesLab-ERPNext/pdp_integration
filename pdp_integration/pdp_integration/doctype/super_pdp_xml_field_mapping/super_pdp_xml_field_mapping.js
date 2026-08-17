// Copyright (c) 2026, Your Organization
// For license information, please see license.txt

frappe.ui.form.on("Super PDP XML Field Mapping", {
	refresh(frm) {
		if (frm.doc.erpnext_doctype) {
			frm.add_custom_button(__("Browse Fields"), () => browse_fields(frm));
		}
	},
	erpnext_doctype(frm) {
		frm.set_value("erpnext_field", "");
	},
});

function browse_fields(frm) {
	frappe.call({
		method: "pdp_integration.erpnext_meta.get_doctype_fields",
		args: { doctype: frm.doc.erpnext_doctype },
	}).then((r) => {
		const fields = r.message || [];
		if (!fields.length) {
			frappe.msgprint(__("No fields found for {0}.", [frm.doc.erpnext_doctype]));
			return;
		}
		const d = new frappe.ui.Dialog({
			title: __("Fields on {0}", [frm.doc.erpnext_doctype]),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "list_html",
					options: `<div class="pdp-field-browser">${fields
						.map(
							(f) => `
						<div class="pdp-field-row" data-fieldname="${frappe.utils.escape_html(f.fieldname)}"
							style="padding:6px 4px; border-bottom:1px solid var(--border-color,#eee); cursor:pointer;">
							<strong>${frappe.utils.escape_html(f.fieldname)}</strong>
							<span class="text-muted small"> - ${frappe.utils.escape_html(f.label || "")} (${frappe.utils.escape_html(f.fieldtype || "")})</span>
						</div>`
						)
						.join("")}</div>`,
				},
			],
		});
		d.$wrapper.find(".pdp-field-row").on("click", function () {
			const fieldname = $(this).data("fieldname");
			frm.set_value("erpnext_field", fieldname);
			d.hide();
		});
		d.show();
	});
}
