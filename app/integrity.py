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

Incremental runs
----------------
A run may fetch only a few new rows whose parents were loaded by an *earlier*
run.  Those parents are not in this run's lists but they are in the database, so
the caller passes ``known`` (keys already stored in PostgreSQL) and a parent
counts as present if it is in this run's data **or** in ``known``.
"""

from dataclasses import replace


MAX_EXAMPLES = 20  # example keys kept per reason in ``details``


def enforce_integrity(
    suppliers, companies, purch_orgs, texts, orders, items, invoices, po_refs,
    known: dict | None = None,
    details: dict | None = None,
) -> tuple[dict, dict]:
    """Return ``(clean_lists, report)``.

    ``report`` maps a human-readable reason to the number of affected rows.

    ``known``   (optional) keys already in PostgreSQL: a dict with the sets
                ``suppliers``, ``orders``, ``items`` ((po, item) tuples) and
                ``invoices`` ((invoice, fiscal_year) tuples).
    ``details`` (optional) dict that is filled with ``reason -> [example keys]``
                (at most ``MAX_EXAMPLES`` each) so the run log can say *which*
                rows were dropped, not just how many.
    """
    report: dict[str, int] = {}
    known = known or {}

    def note(reason: str, n: int = 1, key=None) -> None:
        report[reason] = report.get(reason, 0) + n
        if details is not None and key is not None:
            examples = details.setdefault(reason, [])
            if len(examples) < MAX_EXAMPLES:
                examples.append(str(key))

    supplier_ids = {s.supplier for s in suppliers} | set(known.get("suppliers", ()))

    # --- supplier children: need an existing supplier and a non-empty key ---
    def keep_children(rows, name, *key_fields):
        kept = []
        for r in rows:
            if r.supplier not in supplier_ids:
                note(f"{name}: parent supplier not fetched (dropped)", key=r.supplier)
            elif any(not getattr(r, f) for f in key_fields):
                note(f"{name}: empty key field (dropped)",
                     key=(r.supplier, *(getattr(r, f) for f in key_fields)))
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
            note("purchase_order: supplier not fetched (dropped)", key=po.purchase_order)
        else:
            clean_orders.append(po)
    order_ids = {po.purchase_order for po in clean_orders} | set(known.get("orders", ()))

    # --- items -> purchase order ---
    clean_items = []
    for it in items:
        if it.purchase_order in order_ids and it.purchase_order_item:
            clean_items.append(it)
        else:
            note("purchase_order_item: parent PO not fetched (dropped)",
                 key=(it.purchase_order, it.purchase_order_item))
    item_keys = {(i.purchase_order, i.purchase_order_item) for i in clean_items} | set(known.get("items", ()))

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
                    note("supplier_invoice: references several POs - first one stored in purchase_order",
                         key=(inv.supplier_invoice, inv.fiscal_year))
        elif inv.purchase_order not in order_ids:
            changes["purchase_order"] = None
            note("supplier_invoice: purchase_order not fetched (set to NULL)",
                 key=(inv.supplier_invoice, inv.fiscal_year))
        if inv.supplier is not None and inv.supplier not in supplier_ids:
            changes["supplier"] = None  # invoicing_party column keeps the original value
            note("supplier_invoice: supplier not fetched (supplier set to NULL, invoicing_party kept)",
                 key=(inv.supplier_invoice, inv.fiscal_year))
        clean_invoices.append(replace(inv, **changes) if changes else inv)
    invoice_keys = {(i.supplier_invoice, i.fiscal_year) for i in clean_invoices} | set(known.get("invoices", ()))

    # --- references -> invoice AND po item ---
    clean_refs = []
    for ref in po_refs:
        if (ref.supplier_invoice, ref.fiscal_year) not in invoice_keys:
            note("invoice_po_reference: invoice header missing (dropped)",
                 key=(ref.supplier_invoice, ref.fiscal_year, ref.purchase_order,
                      ref.purchase_order_item, ref.supplier_invoice_item))
        elif (ref.purchase_order, ref.purchase_order_item) not in item_keys:
            note("invoice_po_reference: PO item not fetched (dropped)",
                 key=(ref.supplier_invoice, ref.fiscal_year, ref.purchase_order,
                      ref.purchase_order_item, ref.supplier_invoice_item))
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
