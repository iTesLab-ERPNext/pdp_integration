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
     separate **"Send to SuperPDP"** button that calls function 07
     directly (generates a fresh test invoice, then `POST
     /v1.beta/invoices`) - a real send, so the UI asks for confirmation
     first and shows the returned SuperPDP invoice id.
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

## Notes on scope

The SuperPDP functions in the original ZIP are sandbox/test endpoints
built around `generate_test_invoice` (a server-generated UBL sample) -
they are not a UBL exporter for arbitrary invoice data. "Test with
SuperPDP" on a real ERPNext invoice therefore verifies **connectivity
and the correct role-based flow for that invoice** (seller vs buyer)
using the SuperPDP sandbox test invoice, and links the result to that
ERPNext invoice for audit purposes; it does not yet transform the
ERPNext invoice's own line items into a UBL document. The module is
structured (`pdp_client.py` / `superpdp_functions.py` / `invoices.py`)
so a real UBL exporter can be dropped in later without touching the UI.

## App structure

```
pdp_integration/
  hooks.py
  pdp_client.py            # ported config.js (endpoint + token logic)
  superpdp_functions.py    # ported 01..10 *.js scripts, whitelisted
  invoices.py               # ERPNext invoice list + role-based test pipeline
  pdp_integration/
    doctype/
      super_pdp_settings/       # single doctype, encrypted credentials
      super_pdp_invoice_log/    # audit trail of every SuperPDP call
    page/
      super_pdp_invoices/          # Invoice interface
      super_pdp_function_console/  # Test every function
```
