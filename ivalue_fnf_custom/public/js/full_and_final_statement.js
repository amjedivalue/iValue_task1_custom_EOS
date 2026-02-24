// ======================================================
// Full & Final Statement - Client Script (One File)
// - No UI changes
// - Applies company currency to ALL currency-related fields
// ======================================================

const CHILD_TABLE = "Full and Final Outstanding Statement";
let systemIsFilling = false;

// عندك بالـ Parent الاسم الحقيقي:
const PARENT_CURRENCY_FIELD = "custom_company_currency";

frappe.ui.form.on("Full and Final Statement", {
  onload: function (frm) {
    if (!frm.doc.transaction_date) {
      frm.set_value("transaction_date", frappe.datetime.get_today());
    }

    if (frm.doc.employee) {
      calculate_full_and_final(frm);
    }
  },

  employee: async function (frm) {
    if (!frm.doc.employee) {
      clear_everything(frm);
      return;
    }
    await calculate_full_and_final(frm);
  },

  transaction_date: async function (frm) {
    if (!frm.doc.employee) return;
    await calculate_full_and_final(frm);
  }
});

async function calculate_full_and_final(frm) {
  if (systemIsFilling) return;
  systemIsFilling = true;

  try {
    const response = await frm.call({
      method: "ivalue_fnf_custom.api.full_and_final.get_full_and_final_payload",
      args: {
        employee: frm.doc.employee,
        transaction_date: frm.doc.transaction_date
      }
    });

    const data = response.message;

    if (!data || !data.ok) {
      frappe.msgprint((data && data.msg) ? data.msg : "Calculation failed.");
      return;
    }

    // ✅ Apply currency everywhere (parent + children + session defaults)
    if (data.company_currency) {
      apply_company_currency_everywhere(frm, data.company_currency);
    }

    // تفريغ الجدول
    frm.clear_table("payables");

    // تعبئة صفوف payables
    const rows = data.payables || [];
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const child = frm.add_child("payables");

      child.component = row.component;
      child.day_count = flt(row.day_count || 0);
      child.rate_per_day = flt(row.rate_per_day || 0);
      child.amount = flt(row.amount || 0);

      child.reference_document_type = row.reference_document_type || null;
      child.reference_document = row.reference_document || null;

      // ✅ also push currency into any currency-link fields on the row
      if (data.company_currency) {
        set_currency_link_fields_on_row(child, data.company_currency);
      }
    }

    frm.refresh_field("payables");

    // تحديث الإجمالي
    update_total(frm);

    // Service Details
    frm.set_value("custom_service_years", cint(data.service_years || 0));
    frm.set_value("custom_service_month", cint(data.service_months || 0));
    frm.set_value("custom_service_days", cint(data.service_days || 0));
    frm.set_value("custom_total_of_years", flt(data.total_years || 0));

  } finally {
    systemIsFilling = false;
  }
}

function apply_company_currency_everywhere(frm, currency) {
  // 1) set parent currency field if exists
  if (PARENT_CURRENCY_FIELD in frm.doc) {
    frm.set_value(PARENT_CURRENCY_FIELD, currency);
  }

  // 2) set session default currency (affects ALL Currency fields that rely on defaults)
  try {
    frappe.boot = frappe.boot || {};
    frappe.boot.sysdefaults = frappe.boot.sysdefaults || {};
    frappe.boot.sysdefaults.currency = currency;

    frappe.defaults.set_default("currency", currency);
  } catch (e) {
    // ignore
  }

  // 3) set any Link(Currency) fields on parent doc (if they exist in this doctype)
  set_currency_link_fields_on_doc(frm, currency);

  // 4) set any Link(Currency) fields on ALL child tables rows (if fields exist)
  (frm.meta.fields || [])
    .filter(df => df.fieldtype === "Table" && df.options)
    .forEach(table_df => {
      const tablefield = table_df.fieldname;
      const rows = frm.doc[tablefield] || [];
      rows.forEach(r => set_currency_link_fields_on_row(r, currency));
      frm.refresh_field(tablefield);
    });
}

function set_currency_link_fields_on_doc(frm, currency) {
  (frm.meta.fields || [])
    .filter(df => df.fieldtype === "Link" && df.options === "Currency")
    .forEach(df => {
      if (df.fieldname in frm.doc && !frm.doc[df.fieldname]) {
        frm.set_value(df.fieldname, currency);
      }
    });
}

function set_currency_link_fields_on_row(row, currency) {
  // row is a child doc; we can inspect its meta
  const meta = frappe.get_meta(row.doctype);
  (meta.fields || [])
    .filter(df => df.fieldtype === "Link" && df.options === "Currency")
    .forEach(df => {
      if ((df.fieldname in row) && !row[df.fieldname]) {
        row[df.fieldname] = currency;
      }
    });
}

function clear_everything(frm) {
  systemIsFilling = true;

  frm.clear_table("payables");
  frm.refresh_field("payables");

  frm.set_value("total_payable_amount", 0);

  systemIsFilling = false;
}

frappe.ui.form.on(CHILD_TABLE, {
  day_count: function (frm, cdt, cdn) {
    if (systemIsFilling) return;
    recalc_row_amount(frm, cdt, cdn);
  },

  rate_per_day: function (frm, cdt, cdn) {
    if (systemIsFilling) return;
    recalc_row_amount(frm, cdt, cdn);
  },

  amount: function (frm, cdt, cdn) {
    if (systemIsFilling) return;
    update_total(frm);
  }
});

function recalc_row_amount(frm, cdt, cdn) {
  const row = locals[cdt][cdn];

  const days = flt(row.day_count || 0);
  const rate = flt(row.rate_per_day || 0);
  const amount = flt(days * rate);

  // ✅ keep currency consistent on the row (if there are currency-link fields)
  const cur = frm.doc[PARENT_CURRENCY_FIELD] || frappe.defaults.get_default("currency") || null;
  if (cur) set_currency_link_fields_on_row(row, cur);

  frappe.model.set_value(cdt, cdn, "amount", amount);
  update_total(frm);
}

function update_total(frm) {
  let total = 0;

  const payables = frm.doc.payables || [];
  for (let i = 0; i < payables.length; i++) {
    total = total + flt(payables[i].amount || 0);
  }

  frm.set_value("total_payable_amount", flt(total));
}