# Burundi Compliance — Fork Architecture Guide

> **This document supplements the upstream guide:**
> https://docs.navari.co.ke/burundi-compliance/getting-started/introduction
>
> It covers what is **different** in this fork (`erpchampions/burundi-compliance`) compared to the
> upstream Navari app. Read the upstream guide first for the overall eBMS / OBR concepts, then use
> this document to understand the fork's deployment model.

---

## 1. The key architectural change: Sales Invoice customizations are detached

**Upstream (Navari):** the app injects its OBR fields *directly onto the Sales Invoice doctype*
via `custom/sales_invoice.json` (hundreds of custom fields: submission status, invoice identifier,
eBMS signature, registered number/date, etc.).

**This fork:** those fields have been **removed from Sales Invoice** and moved into a dedicated
**`OBR Invoice Submission`** doctype.

Why this matters for flexible deployment:

- Sales Invoice stays a stock, unmodified ERPNext doctype — no per-install custom-field churn,
  no migration risk when ERPNext changes Sales Invoice.
- All OBR/ebms state lives in one place (`OBR Invoice Submission`), which is simpler to query,
  report on, and export.
- The fork's `custom/sales_invoice.json` is intentionally **empty**:

```json
{ "custom_fields": [], "custom_perms": [], "doctype": "Sales Invoice", "links": [], "property_setters": [] }
```

---

## 2. The OBR Invoice Submission doctype

This is the fork's core record. One `OBR Invoice Submission` is created per submitted
Sales Invoice / POS Invoice.

| Field | Type | Purpose |
|-------|------|---------|
| `sales_invoice` | Link (Sales Invoice) | The source invoice (required) |
| `payment_type` | Select | Cash / Bank / Credit / Others (required) |
| `defer_submission_to_obr` | Check | Skip OBR on submit; send later |
| `submitted_to_obr` | Check | **eBMS Submission** — set when OBR accepted it |
| `ebms_invoice_cancelled` | Check | **eBMS Invoice Cancelled** |
| `invoice_registered_no` | Data | **Invoice Registered No** (from OBR) |
| `invoice_registered_date` | Date | **Invoice Registered Date** (from OBR) |
| `invoice_identifier` | Data | **Invoice Identifier** (from OBR) |
| `einvoice_signatures` | Small Text | **eBMS Signature** (cryptographic, from OBR) |
| `reason_for_creditcancel` | Text Editor | Reason for credit note / cancellation |
| `amended_from` | Link | Source record for amended/credit-note flows |

### Flow

1. User submits a **Sales Invoice** (or POS Invoice).
2. `doc_events` → `create_obr_submission` fires (`overrides/sales_invoice.py`) and creates an
   `OBR Invoice Submission` linked to the invoice.
3. A **Payment Type** prompt appears (Cash / Bank / Credit / Others).
4. The submission is queued to OBR in the background.
5. OBR signs the invoice → the `OBR Invoice Submission` record is updated
   (`submitted_to_obr`, `invoice_registered_no`, `invoice_identifier`, `einvoice_signatures`).

> **Where to check status (this fork):** open the `OBR Invoice Submission` record — **not** the
> Sales Invoice. The upstream docs tell you to look at Sales Invoice fields; in this fork those
> fields no longer exist there.

---

## 3. eBIMS Actions buttons

The **eBIMS Actions** buttons (`Get Invoice`, `Re-Submit`, `Cancel Invoice in OBR`) are driven by
the `OBR Invoice Submission` record associated with the invoice. If no submission record exists
(e.g. a legacy invoice created before the app was installed), the buttons will not appear.

---

## 4. Required one-time configuration

This matches upstream, but two naming details are **load-bearing** in code and easy to get wrong:

### eBMS Endpoint URLs — must be named `SandBox` and `Production`

The doctype is autonamed `format:{environment}`, and `get_urls()` looks the record up **by name**:

```python
# utils/utils.py
if environment == "sandbox":
    endpoint_doc = frappe.get_doc("eBMS Endpoint URLs", "SandBox")
else:
    endpoint = frappe.get_doc("eBMS Endpoint URLs", "Production")
```

So you must create **two** records, named exactly `SandBox` and `Production`, each with the six
endpoints (`login`, `add_invoice`, `get_invoice`, `cancel_invoice`, `check_TIN`, `add_stock_movement`).

### eBMS Settings — autonamed by Company

`eBMS Settings` is autonamed `field:company`, so there is **one record per company**, looked up by
company name in `sales_invoice.py`. The `TIN` field on eBMS Settings is read-only
(`fetch_from: company.tax_id`) — set the TIN on the **Company** doctype's `Tax ID`, not on the
settings form.

### TIN source of truth

The invoice payload reads the TIN from **`company.tax_id`**, not from eBMS Settings:

```python
# utils/build_invoice_payload.py
company_tax_id = company.tax_id
...
"tp_TIN": company_tax_id,
```

---

## 5. Version support

The fork's `pyproject.toml` declares `frappe = ">=15.0.0,<17.0.0"`. It has been installed and
migrated successfully on **Frappe 15.110.0** (ERPNext 15). No v16-only APIs are used.

---

## 6. Migration note for existing Navari installs

If you are migrating a site that previously used the **upstream** app (OBR fields on Sales
Invoice), note:

- The old Sales Invoice custom fields are not migrated into `OBR Invoice Submission` automatically.
- Historical OBR submission state that lived on Sales Invoice will not appear in the new
  `OBR Invoice Submission` list.
- Plan a data backfill if you need to preserve historical signing state.
