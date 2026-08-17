# PDP Integration (`pdp_integration`)

A native Frappe/ERPNext app that connects an existing ERPNext installation
to **SuperPDP** (`https://api.superpdp.tech`), the sandbox "Plateforme de
Dematerialisation Partenaire" used for the French e-invoicing reform.

It is built directly on top of the SuperPDP test scripts that were
provided (`01_seller_token.js` ... `10_send_paid_event.js` plus
`config.js`): every one of those functions has been **ported 1:1 to
Python** (same endpoint, same headers, same request shape, same order of
operations) because a Frappe site's backend runs Python, not Node.js.
Nothing about the SuperPDP request logic was reinvented - it was moved
into a place ERPNext can call it from, and wired up to real ERPNext data.

## What you get

1. **Super PDP Settings** (System Manager only) - a single doctype to
   configure:
   - `SUPERPDP_ENDPOINT` (default `https://api.superpdp.tech`)
   - `SUPERPDP_BURGERQUEEN_CLIENT_ID` / `SUPERPDP_BURGERQUEEN_CLIENT_SECRET` (seller)
   - `SUPERPDP_TRICATEL_CLIENT_ID` / `SUPERPDP_TRICATEL_CLIENT_SECRET` (buyer)

   Secrets use Frappe's built-in **Password** fieldtype: they are
   encrypted at rest (`__Auth` table) and the value is *never* sent back
   to the browser after saving - the client JS only ever sees a masked
   placeholder. All SuperPDP HTTP calls happen server-side
   (`pdp_client.py`, `superpdp_functions.py`).

2. **SuperPDP Invoices** page (`/app/super-pdp-invoices`) - lists ERPNext
   **Sales Invoices** and **Purchase Invoices** with a **"Test with
   SuperPDP"** button per row. Role is auto-detected:
   - `Sales Invoice` -> your company is the **seller** -> **"Test with
     SuperPDP"** runs the seller pipeline (token -> company lookup ->
     generate test invoice -> validate). Sales Invoice rows also get a
     separate **"Send to SuperPDP"** button that builds a real UBL
     invoice from *that invoice's own* customer, line items, quantities,
     prices, taxes and totals (see "Sending real invoice data" below)
     and sends it via function 07 (`POST /v1.beta/invoices`) - a real
     send, so the UI asks for confirmation first and shows the returned
     SuperPDP invoice id.
   - `Purchase Invoice` -> your company is the **buyer** -> **"Test with
     SuperPDP"** runs the buyer pipeline (token -> list invoices visible
     to the buyer, with a best-effort match against the ERPNext invoice
     number). There's no "Send" button here - a buyer doesn't send.

   Every step (test or send) is logged to **Super PDP Invoice Log**,
   linked back to the ERPNext invoice - sent invoices also store the
   returned SuperPDP invoice id - so results are fully auditable.

3. **SuperPDP Function Console** page (`/app/super-pdp-function-console`)
   - every SuperPDP function from the ZIP, individually testable:

   | # | Function | Source file | Endpoint |
   |---|----------|-------------|----------|
   | 01 | Seller OAuth Token | `01_seller_token.js` | `POST /oauth2/token` |
   | 02 | Buyer OAuth Token | `02_buyer_token.js` | `POST /oauth2/token` |
   | 03 | Seller Company Info | `03_seller_company.js` | `GET /v1.beta/companies/me` |
   | 04 | Generate Test Invoice | `04_generate_invoice.js` | `GET /v1.beta/invoices/generate_test_invoice` |
   | 05 | Validate Invoice | `05_validate_invoice.js` | `POST /v1.beta/validation_reports` |
   | 06 | List Buyer Invoices | `06_list_buyer_invoices.js` | `GET /v1.beta/invoices` |
   | 07 | Send Invoice | `07_send_invoice.js` | `POST /v1.beta/invoices` |
   | 08 | Check Received Invoice | `08_check_received_invoice.js` | `GET /v1.beta/invoices` |
   | 09 | Check Invoice Status | `09_check_invoice_status.js` | `GET /v1.beta/invoices/{id}` |
   | 10 | Send Paid ("Encaissee") Event | `10_send_paid_event.js` | `POST /v1.beta/invoice_events` |

   Each row shows function name, related JS file, a **Run Test** button,
   live request status, response, and error message - plus a **"Run All
   (Recommended Order)"** button that chains 01 -> 10, reusing cached
   state between steps (test invoice XML, uploaded invoice id) the same
   way the original scripts reused local files.

4. **SuperPDP XML Configuration** page (`/app/super-pdp-xml-configuration`)
   - select a Company/Customer/Sales Invoice and see, before anything is
   sent: every XML field, its ERPNext source, its live resolved value,
   and its status (Mapped/Computed/Missing/Invalid), grouped by section
   with Invoice Lines and Tax Subtotals resolved per line/rate. Includes
   a validation report, a full **Preview XML** viewer, and a **Send to
   SuperPDP** action once everything checks out. See "XML field mapping"
   below for how the mapping itself is configured and stored.

## Sidebar / Desk menu

Installing the app adds a **"PDP Integration"** entry to the Frappe
Desk sidebar automatically - no manual setup step. This is a standard
Workspace (`pdp_integration/pdp_integration/workspace/pdp_integration`),
synced into the `Workspace` doctype the same way `bench install-app`
syncs every other standard doc (Page, Report, DocType, ...), so it
appears right after `bench --site <site> install-app pdp_integration`
(the app's `after_install` hook also clears the desk cache so it shows
up without a manual browser refresh cache-bust).

It matches the same conventions ERPNext's own module workspaces use:

- **Icon/style**: `octicon octicon-plug`, green indicator - the same
  icon/color declared in `hooks.py` (`app_icon` / `app_color`), so the
  sidebar entry and the app's own identity match.
- **Structure**: a header, a short description, and one shortcut per
  screen - Super PDP Settings, SuperPDP Invoices, SuperPDP Function
  Console, and the Super PDP Invoice Log list - each shortcut using the
  same icon language (gear for settings, list for logs, etc.) as other
  workspace shortcuts in ERPNext.
- **Permissions**: the workspace itself is restricted to the same roles
  already enforced on the two Pages and the log doctype - **System
  Manager**, **Accounts Manager**, **Accounts User** - via the
  Workspace's `roles` table, so only those roles see it in their
  sidebar at all; other users won't see a dead link.
- **Navigation**: each shortcut routes exactly like ERPNext's own
  shortcuts do - the Settings shortcut opens the Single doctype's Form
  directly, the Invoice Log shortcut opens its List view, and the two
  Page shortcuts open their respective pages - no extra clicks or
  custom routing logic.

If you ever need to customize the layout (add cards, reorder
shortcuts, etc.), open the workspace in the Desk and use **Edit
Workspace** - Frappe will keep your site's copy in sync with new
releases of this app unless you explicitly detach it.

For very old sites (pre-Workspace, Frappe < v13) there's also a
`config/desktop.py` fallback using the same icon/color, so the module
still shows up as a desktop icon on legacy desk versions.

## Installation

This is a standard Frappe app - `bench get-app` needs either a git URL or
a local path (a brand-new custom app has no public registry entry, so
pick whichever fits your setup):

```bash
# Option A: from a git repo you control
bench get-app pdp_integration https://github.com/<you>/pdp_integration.git
bench --site <your-site> install-app pdp_integration

# Option B: from a local path (e.g. this extracted folder)
bench get-app pdp_integration /path/to/pdp_integration
bench --site <your-site> install-app pdp_integration

# then, on any site update:
bench --site <your-site> migrate
```

`erpnext` must already be installed on the site (declared as
`required_apps` in `hooks.py`), since the invoice interface reads
ERPNext's `Sales Invoice` / `Purchase Invoice` doctypes.

## First-time setup

1. Go to **Super PDP Settings** (`/app/super-pdp-settings`) and fill in
   the endpoint + seller/buyer client id & secret. Use **Test Seller
   Connection** / **Test Buyer Connection** to confirm the credentials
   work.
2. Open **SuperPDP Invoices** to test real Sales/Purchase Invoices
   against the SuperPDP sandbox.
3. Open **SuperPDP Function Console** to exercise every SuperPDP
   function individually, or run the full recommended sequence.

## XML field mapping - see it before you send it

**"Send to SuperPDP" sends that invoice's own data - not the SuperPDP
sandbox sample - and every field it sends is driven by an editable
mapping table, not hardcoded Python.** Open **SuperPDP XML
Configuration** (`/app/super-pdp-xml-configuration`), pick a Company /
Customer / Sales Invoice, and you get exactly what was asked for:

> Before an XML is sent, you can see every XML field that will be sent,
> its ERPNext source field, and its actual live value from ERPNext.

- **Mapping table**: every XML field, grouped by section, shows its
  ERPNext source (`Doctype.field`), its transformation, its **live
  resolved value from the selected invoice**, and a status badge -
  `Mapped` / `Computed` / `Static` / `Missing Required` / `Optional
  Unmapped` / `Invalid`. Invoice Lines and Tax Subtotals get their own
  sub-tables, resolved per line item / per VAT rate against the real
  data (not just a first-line example).
- **Validation report**: required-but-missing or invalid fields are
  listed explicitly, and the page shows "Cannot send" until they're
  fixed - nothing is silently sent half-built.
- **Preview XML**: renders the exact XML that would be sent, in a
  read-only code viewer, with a **Send to SuperPDP** action right there
  once you've reviewed it.
- **Reset Mapping to Defaults** (menu): discards local edits and
  reseeds from the app's shipped defaults if you want to start over.

**On sites where `pdp_integration` was already installed** before this
feature existed: the default template/mapping are created automatically
on the next `bench migrate` (via `after_migrate`), and the page itself
detects an unseeded site and offers a one-click **Create Default XML
Configuration** button too - no reinstall needed either way. Both paths
are idempotent (`xml_seed.seed_defaults()` / `seed_all()`): they only
create what's missing and never touch mapping rows you've already
edited - only the explicit **Reset Mapping to Defaults** action does that.

### How the mapping works

- **`Super PDP XML Template`** stores the reference XML (seeded from
  the SuperPDP sample) and its parsed field-path structure
  (`xml_template.py` parses it generically - it doesn't hardcode which
  paths exist, so a second template/version can be added later just by
  saving a new document).
- **`Super PDP XML Field Mapping`** is the actual configuration: one row
  per XML field/attribute, with its ERPNext doctype + field, a curated
  transformation (`Currency Code (ISO)`, `Date (YYYY-MM-DD)`, `SIREN
  from SIRET`, `UOM Code (UN/ECE)`, `Static Value`, `Computed by
  Engine`, ...), and required/optional status. Seeded automatically on
  install from `xml_mapping_defaults.py` (which mirrors what the old
  hardcoded builder did, plus two fields it was missing:
  `Delivery/ActualDeliveryDate` and the buyer's `PartyIdentification/ID`).
  Edit rows directly in the list, or use **Browse Fields** on a row to
  pick a real field from the ERPNext doctype's actual metadata
  (`erpnext_meta.py` - never a hardcoded field list).
- **`xml_mapper.py`** is the single engine behind both the preview page
  and the real send: it resolves every mapping row against live ERPNext
  data (`resolve_all()`) and renders the final XML from those same
  resolved values (`render_invoice_xml()`) - there's one XML generation
  path, not two. `ubl_builder.py` is now a thin backward-compatible
  shim so `invoices.py`'s existing import keeps working unchanged.
- Fields left unmapped and marked optional (like `Delivery`, which has
  no standard ERPNext Sales Invoice field) are simply **omitted** from
  the XML rather than filled with an invented value. Required fields
  left unmapped block sending with a specific error naming the field.

**Required configuration** for a send to succeed, because ERPNext has no
native SIRET field and PDP routing needs one:

| Field | Where | Required for |
|---|---|---|
| Seller SIRET | Super PDP Settings | every send |
| Company Tax ID | Company master (`tax_id`) | every send |
| Buyer SIRET | Customer's `custom_siret` field, or Default Buyer SIRET in Super PDP Settings | every send |

`SuperPDP Function Console`'s individual "07 Send Invoice" test button
is unchanged and still sends the cached sandbox test invoice (from "04
Generate Test Invoice") - that console is for exercising the raw
SuperPDP API generically, independent of any specific ERPNext invoice.
The **SuperPDP Invoices** page's "Send to SuperPDP" button and the new
**SuperPDP XML Configuration** page's "Send to SuperPDP" both call the
same `invoices.send_invoice_to_superpdp`, which now runs through
`xml_mapper.py` - so what you preview is exactly what gets sent.

## Notes on scope

"Test with SuperPDP" still uses the SuperPDP sandbox `generate_test_invoice`
for connectivity/flow checks (token, company lookup, validate) - it's a
quick health check, not a send. "Send to SuperPDP" is the one that uses
real ERPNext invoice data (see "XML field mapping" above). The
buyer-side flow still only *lists* invoices visible to the buyer (that's
what functions 06/08 do) - there is no SuperPDP function for a buyer to
send anything.

## App structure

```
pdp_integration/
  hooks.py
  pdp_client.py            # ported config.js (endpoint + token logic)
  superpdp_functions.py    # ported 01..10 *.js scripts, whitelisted
  ubl_builder.py            # backward-compat shim -> xml_mapper.render_invoice_xml
  xml_sample.py              # the SuperPDP sample XML, embedded as reference data
  xml_template.py            # generic XML -> field-path parser (any UBL-shaped XML)
  xml_mapping_defaults.py    # default ERPNext -> XML field mapping (seed data)
  xml_mapper.py               # the mapping engine: resolve_all() + render_invoice_xml()
  xml_seed.py                 # creates/resets the default template + mapping rows
  erpnext_meta.py             # read-only ERPNext doctype/field/record discovery
  invoices.py               # ERPNext invoice list + role-based test/send pipeline
  pdp_integration/
    doctype/
      super_pdp_settings/           # single doctype, encrypted credentials
      super_pdp_invoice_log/        # audit trail of every SuperPDP call
      super_pdp_xml_template/       # reference XML + parsed structure
      super_pdp_xml_field_mapping/  # the editable ERPNext -> XML field mapping
    page/
      super_pdp_invoices/               # Invoice interface
      super_pdp_function_console/       # Test every function
      super_pdp_xml_configuration/      # XML field mapping / preview / validation
```
