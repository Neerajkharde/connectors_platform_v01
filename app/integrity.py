"""
Referential-integrity step between *mapping* and *persisting*.

Why it is needed
----------------
The PostgreSQL schema has foreign keys.  The data comes from several
independent SAP calls, and any of them can return something that points at a
row we did not (or could not) fetch, e.g.

* an invoice whose ``InvoicingParty`` is a supplier outside the fetched set,
* an invoice-to-PO reference whose invoice header returned 404,
* a reference to a PO item that was not extracted.

One such row makes PostgreSQL reject the INSERT, and because everything runs in
a single transaction the *entire* load is rolled back.  This module repairs or
removes those rows beforehand and reports exactly what it did, so the data that
is loaded is consistent and nothing is dropped silently.
"""

from dataclasses import replace


def enforce_integrity(
    suppliers, companies, purch_orgs, texts, orders, items, invoices, po_refs
) -> tuple[dict, dict]:
    """Return ``(clean_lists, report)``.

    ``report`` maps a human-readable reason to the number of affected rows.
    """
    report: dict[str, int] = {}

    def note(reason: str, n: int = 1) -> None:
        report[reason] = report.get(reason, 0) + n

    supplier_ids = {s.supplier for s in suppliers}

    # --- supplier children: need an existing supplier and a non-empty key ---
    def keep_children(rows, name, *key_fields):
        kept = []
        for r in rows:
            if r.supplier not in supplier_ids:
                note(f"{name}: parent supplier not fetched (dropped)")
            elif any(not getattr(r, f) for f in key_fields):
                note(f"{name}: empty key field (dropped)")
            else:
                kept.append(r)
        return kept

    companies = keep_children(companies, "supplier_company", "company_code")
    purch_orgs = keep_children(purch_orgs, "supplier_purchasing_org", "purchasing_organization")
    texts = keep_children(texts, "supplier_text", "language", "text_type")

    # --- purchase orders -> supplier ---
    clean_orders = []
    for po in orders:
        if po.supplier is not None and po.supplier not in supplier_ids:
            note("purchase_order: supplier not fetched (dropped)")
        else:
            clean_orders.append(po)
    order_ids = {po.purchase_order for po in clean_orders}

    # --- items -> purchase order ---
    clean_items = []
    for it in items:
        if it.purchase_order in order_ids and it.purchase_order_item:
            clean_items.append(it)
        else:
            note("purchase_order_item: parent PO not fetched (dropped)")
    item_keys = {(i.purchase_order, i.purchase_order_item) for i in clean_items}

    # --- invoices -> supplier / purchase order ---
    # SAP's invoice header has no PO field; derive it from the item references.
    pos_by_invoice: dict[tuple[str, str], list[str]] = {}
    for ref in po_refs:
        if ref.purchase_order in order_ids:
            pos_by_invoice.setdefault((ref.supplier_invoice, ref.fiscal_year), []).append(
                ref.purchase_order
            )

    clean_invoices = []
    for inv in invoices:
        changes = {}
        if inv.purchase_order is None:
            candidates = sorted(set(pos_by_invoice.get((inv.supplier_invoice, inv.fiscal_year), [])))
            if candidates:
                changes["purchase_order"] = candidates[0]
                if len(candidates) > 1:
                    note("supplier_invoice: references several POs - first one stored in purchase_order")
        elif inv.purchase_order not in order_ids:
            changes["purchase_order"] = None
            note("supplier_invoice: purchase_order not fetched (set to NULL)")
        if inv.supplier is not None and inv.supplier not in supplier_ids:
            changes["supplier"] = None  # invoicing_party column keeps the original value
            note("supplier_invoice: supplier not fetched (supplier set to NULL, invoicing_party kept)")
        clean_invoices.append(replace(inv, **changes) if changes else inv)
    invoice_keys = {(i.supplier_invoice, i.fiscal_year) for i in clean_invoices}

    # --- references -> invoice AND po item ---
    clean_refs = []
    for ref in po_refs:
        if (ref.supplier_invoice, ref.fiscal_year) not in invoice_keys:
            note("invoice_po_reference: invoice header missing (dropped)")
        elif (ref.purchase_order, ref.purchase_order_item) not in item_keys:
            note("invoice_po_reference: PO item not fetched (dropped)")
        else:
            clean_refs.append(ref)

    clean = {
        "suppliers": suppliers,
        "companies": companies,
        "purch_orgs": purch_orgs,
        "texts": texts,
        "orders": clean_orders,
        "items": clean_items,
        "invoices": clean_invoices,
        "po_refs": clean_refs,
    }
    return clean, report
