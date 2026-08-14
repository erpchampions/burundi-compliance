import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.model.document import Document

from ..utils.invoice_signature import create_invoice_signature
from .format_date_and_time import date_time_format


def get_or_create_obr_submission(doc: Document) -> Document:
    """Get or create OBR Invoice Submission record for a Sales Invoice"""
    existing = frappe.db.exists(
        "OBR Invoice Submission", {"sales_invoice": doc.name}
    )
    if existing:
        return frappe.get_doc("OBR Invoice Submission", existing)
    else:
        obr_doc = frappe.new_doc("OBR Invoice Submission")
        obr_doc.sales_invoice = doc.name
        obr_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return obr_doc


def build_invoice_payload(doc: Document, settings_doc: Document) -> dict:
    company = frappe.get_doc("Company", doc.company)
    company_address = get_company_address_details(doc)
    company_tax_id = company.tax_id
    tp_phone_no = company.phone_no
    tp_email = company.email
    formatted_date_data = date_time_format(doc)
    invoice_signature = create_invoice_signature(
        doc, settings_doc.system_identification_given_by_obr
    )

    if doc.doctype == "Sales Invoice":
        # Store invoice identifier in OBR Invoice Submission
        obr_submission = get_or_create_obr_submission(doc)
        frappe.db.set_value(
            "OBR Invoice Submission",
            obr_submission.name,
            "invoice_identifier",
            invoice_signature,
            update_modified=False,
        )
        payment_type = get_payment_method(obr_submission.payment_type)
    else:
        # POS Invoice — store on doc directly as before
        frappe.db.set_value(
            doc.doctype,
            doc.name,
            "custom_invoice_identifier",
            invoice_signature,
            update_modified=False,
        )
        payment_type = get_payment_method(obr_submission.payment_type)
        
    confirm_tin_verified(doc.customer)
    if doc.doctype == "POS Invoice":
        exempt_from_sales_tax = 0
    else:
        exempt_from_sales_tax = doc.get("exempt_from_sales_tax") or 0

    invoice_data = {
        "invoice_number": doc.name,
        "invoice_date": formatted_date_data[0],
        "invoice_type": "FN",
        "tp_type": (
            1 if settings_doc.type_of_taxpayer == "pour personne physique et" else 2
        ),
        "tp_name": doc.company,
        "tp_TIN": company_tax_id,
        "tp_address_province": company_address.get("tp_address_province"),
        "tp_phone_number": tp_phone_no,
        "tp_address_commune": company_address.get("tp_address_commune"),
        "tp_address_avenue": company_address.get("tp_address_avenue"),
        "tp_address_quartier": company_address.get("tp_address_quartier"),
        "tp_address_rue": company_address.get("tp_address_rue"),
        "tp_address_number": company_address.get("tp_address_number"),
        "tp_trade_number": settings_doc.the_taxpayers_commercial_register_number,
        "tp_email": tp_email,
        "vat_taxpayer": (
            0 if settings_doc.subject_to_vat == "pour un non assujetti ou" else 1
        ),
        "ct_taxpayer": (
            0
            if settings_doc.subject_to_consumption_tax == "pour un non assujetti ou"
            else 1
        ),
        "tl_taxpayer": (
            0
            if settings_doc.subject_to_flatrate_withholding_tax
            == "pour un non assujetti ou"
            else 1
        ),
        "tp_fiscal_center": settings_doc.the_taxpayers_tax_center,
        "tp_activity_sector": settings_doc.taxpayers_sector_of_activity,
        "tp_legal_form": settings_doc.taxpayers_legal_form,
        "payment_type": payment_type,
        "invoice_currency": doc.currency,
        "customer_name": doc.customer_name,
        "customer_TIN": doc.tax_id if doc.tax_id else "",
        "customer_address": doc.customer_address if doc.customer_address else "",
        "vat_customer_payer": exempt_from_sales_tax,
        "invoice_ref": "",
        "cn_motif": "",
        "invoice_identifier": invoice_signature,
        "invoice_items": get_invoice_items(doc),
    }

    if doc.is_return:
        if doc.doctype == "Sales Invoice":
            # Get reason from OBR Invoice Submission
            obr_submission = get_or_create_obr_submission(doc)
            if not obr_submission.reason_for_creditcancel:
                frappe.throw(
                    _(
                        "Please provide a reason for credit note in the OBR Invoice Submission record."
                    )
                )
            soup = BeautifulSoup(obr_submission.reason_for_creditcancel, "html.parser")
            ct_motif = soup.get_text()
        else:
            # POS Invoice — use custom field as before
            if not doc.custom_reason_for_creditcancel:
                frappe.throw(
                    _(
                        "Please provide a reason for credit note in the 'Reason for Credit/Cancellation' field."
                    )
                )
            soup = BeautifulSoup(doc.custom_reason_for_creditcancel, "html.parser")
            ct_motif = soup.get_text()

        invoice_data.update(
            {
                "invoice_ref": doc.return_against,
                "cn_motif": ct_motif,
                "invoice_type": "FA",
            }
        )

        if doc.doctype != "Sales Invoice" and doc.creating_payment_entry:
            invoice_data["invoice_type"] = "RC"

    return invoice_data


def get_company_address_details(doc: Document) -> dict:
    address_details = {}
    links = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Company",
            "link_name": doc.company,
            "parenttype": "Address",
        },
        fields=["parent"],
    )
    if links:
        address = frappe.get_doc("Address", links[0].parent)
        address_details = {
            "tp_address_province": address.state,
            "tp_address_commune": address.custom_commune,
            "tp_address_quartier": address.custom_quartier,
            "tp_address_avenue": address.custom_avenue,
            "tp_address_rue": address.custom_rue,
            "tp_address_number": address.custom_numero,
        }
    return address_details


def confirm_tin_verified(customer: str):
    customer = frappe.get_doc("Customer", customer)

    if customer.custom_gst_category == "Registered":
        if not customer.custom_tin_verified:
            frappe.throw(
                "Please Verify the TIN number of this customer on <b>Customer</b> doctype"
            )
            frappe.log_error(
                "TIN Verification Error",
                f"TIN number for customer {customer.name} is not verified.",
            )


def get_payment_method(payment_type: str) -> str:
    if not payment_type:
        return "4"
    payment_type_lower = payment_type.lower()
    if "bank" in payment_type_lower:
        return "2"
    elif "cash" in payment_type_lower:
        return "1"
    elif "credit" in payment_type_lower:
        return "3"
    else:
        return "4"


def get_item_vat_map(doc) -> dict:
    """Return per-item VAT amount keyed by item row name.

    ERPNext v16 stores an item-wise tax breakdown in the ``Item Wise Tax Detail``
    child table. v15 has no such table — taxes are held on ``doc.taxes`` and
    allocated to items by their net amount. Handle both so the app runs on v15
    and v16.
    """
    vat_map = {}

    if frappe.db.exists("DocType", "Item Wise Tax Detail"):
        rows = frappe.get_all(
            "Item Wise Tax Detail",
            filters={"parent": doc.name},
            fields=["item_row", "rate", "amount"],
        )
        for row in rows:
            if (row.get("rate") or 0) > 0:
                vat_map[row.get("item_row")] = vat_map.get(row.get("item_row"), 0) + (
                    row.get("amount") or 0
                )
        return vat_map

    # v15 fallback: allocate invoice-level taxes to items by net amount.
    for item in doc.items:
        total_vat = 0.0
        net_amount = abs(item.get("net_amount") or 0)
        for tax in doc.get("taxes") or []:
            if tax.get("charge_type") == "On Net Total" and (tax.get("rate") or 0) > 0:
                total_vat += net_amount * tax.get("rate") / 100
        vat_map[item.name] = total_vat

    return vat_map


def get_invoice_items(doc):
    items = []

    item_vat_map = get_item_vat_map(doc)

    for item in doc.items:
        total_vat = abs(item_vat_map.get(item.name, 0) or 0)

        item_designation = (
            item.description
            if item.description
            else (
                f"{item.item_code}-{item.batch_no}" if item.batch_no else item.item_code
            )
        )

        item_amount = abs(item.amount)

        items.append(
            {
                "item_code": item.item_code,
                "item_designation": item_designation,
                "item_quantity": abs(item.qty),
                "item_price": item.rate,
                "item_total_amount": item_amount,
                "vat": total_vat,
                "item_ct": "0",
                "item_tl": "0",
                "item_price_nvat": item_amount,
                "item_price_wvat": item_amount + total_vat,
            }
        )

    return items