import frappe

def handle_sales_invoice_submission(
    response: dict, document_name: str, doctype: str
) -> None:
    try:
        
        invoice_number = response.get("result", {}).get("invoice_number")
        invoice_registered_number = response.get("result", {}).get(
            "invoice_registered_number"
        )
        invoice_registered_date = response.get("result", {}).get(
            "invoice_registered_date"
        )
        electronic_signature = response.get("electronic_signature")

        if doctype == "Sales Invoice":
            # Update OBR Invoice Submission doctype instead of Sales Invoice
            existing = frappe.db.exists(
                "OBR Invoice Submission", {"sales_invoice": document_name}
            )
            if existing:
                frappe.db.set_value("OBR Invoice Submission", existing, {
                    "submitted_to_obr": 1,
                    "einvoice_signatures": electronic_signature,
                    "invoice_registered_no": invoice_registered_number,
                    "invoice_registered_date": invoice_registered_date,
                })
            else:
                frappe.log_error(
                    f"No OBR Invoice Submission found for Sales Invoice {document_name}",
                    "OBR Invoice Submission Missing"
                )
        else:

            # POS Invoice — update fields directly as before
            data_to_update = {
                "custom_einvoice_signatures": electronic_signature,
                "custom_invoice_registered_no": invoice_registered_number,
                "custom_invoice_registered_date": invoice_registered_date,
                "custom_submitted_to_obr": 1,
            }
            frappe.db.set_value(doctype, document_name, data_to_update)

        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Error updating {doctype} {document_name}: {str(e)}")

def handle_sales_invoice_cancellation(
    response: dict, document_name: str, doctype: str
) -> None:
    try:
        if doctype == "Sales Invoice":
            # Update OBR Invoice Submission doctype instead of Sales Invoice
            existing = frappe.db.exists(
                "OBR Invoice Submission", {"sales_invoice": document_name}
            )
            if existing:
                frappe.db.set_value("OBR Invoice Submission", existing, {
                    "ebms_invoice_cancelled": 1,
                })
        else:
            # POS Invoice — update fields directly as before
            data_to_update = {
                "custom_ebms_invoice_cancelled": 1,
            }
            frappe.db.set_value(doctype, document_name, data_to_update)

        frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"Error updating {doctype} {document_name}: {str(e)}")