

const PAYABLES_CHILD_DOTYPE = "Full and Final Outstanding Statement";
let isAutoFilling = false;

// اسم حقل العملة في الـ Parent
const PARENT_CURRENCY_FIELD = "custom_company_currency";

frappe.ui.form.on("Full and Final Statement", {
  onload(frm) {
    if (!frm.doc.transaction_date) {
      frm.set_value("transaction_date", frappe.datetime.get_today());
    }

    if (frm.doc.employee) {
      runFullAndFinalCalculation(frm);
    }
  },

  employee: async function (frm) {
    if (!frm.doc.employee) {
      resetFormValues(frm);
      return;
    }
    await runFullAndFinalCalculation(frm);
  },

  transaction_date: async function (frm) {
    if (!frm.doc.employee) return;
    await runFullAndFinalCalculation(frm);
  }
});

async function runFullAndFinalCalculation(frm) {
  if (isAutoFilling) return;
  isAutoFilling = true;

  try {
    const res = await frm.call({
      method: "ivalue_fnf_custom.api.full_and_final.get_full_and_final_payload",
      args: {
        employee: frm.doc.employee,
        transaction_date: frm.doc.transaction_date
      }
    });

    const payload = res.message;

    if (!payload || !payload.ok) {
      frappe.msgprint(payload?.msg || "Calculation failed.");
      return;
    }

    // ✅ apply currency everywhere
    if (payload.company_currency) {
      applyCurrencyEverywhere(frm, payload.company_currency);
    }

    // clear payables table
    frm.clear_table("payables");

    // fill payables rows
    const payableRows = payload.payables || [];
    for (let i = 0; i < payableRows.length; i++) {
      const rowData = payableRows[i];
      const childRow = frm.add_child("payables");

      childRow.component = rowData.component;
      childRow.day_count = flt(rowData.day_count || 0);
      childRow.rate_per_day = flt(rowData.rate_per_day || 0);
      childRow.amount = flt(rowData.amount || 0);

      childRow.reference_document_type = rowData.reference_document_type || null;
      childRow.reference_document = rowData.reference_document || null;

      // ✅ push currency into any Link(Currency) fields inside the row
      if (payload.company_currency) {
        setCurrencyLinksOnChildRow(childRow, payload.company_currency);
      }
    }

    frm.refresh_field("payables");

    // update total
    updateTotalPayable(frm);

    // service details
    frm.set_value("custom_service_years", cint(payload.service_years || 0));
    frm.set_value("custom_service_month", cint(payload.service_months || 0));
    frm.set_value("custom_service_days", cint(payload.service_days || 0));
    frm.set_value("custom_total_of_years", flt(payload.total_years || 0));

  } finally {
    isAutoFilling = false;
  }
}

function applyCurrencyEverywhere(frm, currency) {
  // 1) set parent currency field
  if (PARENT_CURRENCY_FIELD in frm.doc) {
    frm.set_value(PARENT_CURRENCY_FIELD, currency);
  }

  // 2) set system defaults currency (helps Currency fields that depend on defaults)
  try {
    frappe.boot = frappe.boot || {};
    frappe.boot.sysdefaults = frappe.boot.sysdefaults || {};
    frappe.boot.sysdefaults.currency = currency;
    frappe.defaults.set_default("currency", currency);
  } catch (e) {
    // ignore
  }

  // 3) set any Link(Currency) fields on parent doctype
  setCurrencyLinksOnParentDoc(frm, currency);

  // 4) set any Link(Currency) fields on ALL child tables
  (frm.meta.fields || [])
    .filter(df => df.fieldtype === "Table" && df.options)
    .forEach(tableDf => {
      const tableFieldname = tableDf.fieldname;
      const tableRows = frm.doc[tableFieldname] || [];
      tableRows.forEach(r => setCurrencyLinksOnChildRow(r, currency));
      frm.refresh_field(tableFieldname);
    });
}

function setCurrencyLinksOnParentDoc(frm, currency) {
  (frm.meta.fields || [])
    .filter(df => df.fieldtype === "Link" && df.options === "Currency")
    .forEach(df => {
      if (df.fieldname in frm.doc && !frm.doc[df.fieldname]) {
        frm.set_value(df.fieldname, currency);
      }
    });
}

function setCurrencyLinksOnChildRow(row, currency) {
  const meta = frappe.get_meta(row.doctype);
  (meta.fields || [])
    .filter(df => df.fieldtype === "Link" && df.options === "Currency")
    .forEach(df => {
      if (df.fieldname in row && !row[df.fieldname]) {
        row[df.fieldname] = currency;
      }
    });
}

function resetFormValues(frm) {
  isAutoFilling = true;

  frm.clear_table("payables");
  frm.refresh_field("payables");

  frm.set_value("total_payable_amount", 0);

  isAutoFilling = false;
}

frappe.ui.form.on(PAYABLES_CHILD_DOTYPE, {
  day_count(frm, cdt, cdn) {
    if (isAutoFilling) return;
    recalcChildAmount(frm, cdt, cdn);
  },

  rate_per_day(frm, cdt, cdn) {
    if (isAutoFilling) return;
    recalcChildAmount(frm, cdt, cdn);
  },

  amount(frm) {
    if (isAutoFilling) return;
    updateTotalPayable(frm);
  }
});

function recalcChildAmount(frm, cdt, cdn) {
  const row = locals[cdt][cdn];

  const days = flt(row.day_count || 0);
  const rate = flt(row.rate_per_day || 0);
  const amount = flt(days * rate);

  // ✅ keep currency consistent on the row
  const currency =
    frm.doc[PARENT_CURRENCY_FIELD] ||
    frappe.defaults.get_default("currency") ||
    null;

  if (currency) setCurrencyLinksOnChildRow(row, currency);

  frappe.model.set_value(cdt, cdn, "amount", amount);
  updateTotalPayable(frm);
}

function updateTotalPayable(frm) {
  let total = 0;

  const payables = frm.doc.payables || [];
  for (let i = 0; i < payables.length; i++) {
    total += flt(payables[i].amount || 0);
  }

  frm.set_value("total_payable_amount", flt(total));
}