const CHILD_TABLE = "Full and Final Outstanding Statement";

// هذا متغير عشان نمنع اللوب
let systemIsFilling = false;


// ======================================================
// Parent DocType
// ======================================================
frappe.ui.form.on("Full and Final Statement", {

  onload(frm) {

    // لو transaction_date فاضي نحطه اليوم
    if (!frm.doc.transaction_date) {
      frm.set_value("transaction_date", frappe.datetime.get_today());
    }

    // لو الموظف موجود نحسب مباشرة
    if (frm.doc.employee) {
      calculate_full_and_final(frm);
    }
  },

  async employee(frm) {

    // لو شال الموظف → نفرغ كل شيء
    if (!frm.doc.employee) {
      clear_everything(frm);
      return;
    }

    // لو اختار موظف → نحسب
    await calculate_full_and_final(frm);
  },

  async transaction_date(frm) {
    if (!frm.doc.employee) return;
    await calculate_full_and_final(frm);
  }
});


// ======================================================
// الحساب الرئيسي
// ======================================================
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
      frappe.msgprint(data?.msg || "صار خطأ بالحساب");
      return;
    }

    // نفرغ الجدول
    frm.clear_table("payables");

    // نعبي الصفوف من السيرفر
    (data.payables || []).forEach(row => {

      let child = frm.add_child("payables");

      child.component = row.component;
      child.day_count = flt(row.day_count);
      child.rate_per_day = flt(row.rate_per_day);
      child.amount = flt(row.amount);

    });

    frm.refresh_field("payables");

    // نحسب التوتل من الجدول
    update_total(frm);

  } finally {
    systemIsFilling = false;
  }
}


// ======================================================
// لو فضي الموظف
// ======================================================
function clear_everything(frm) {

  systemIsFilling = true;

  frm.clear_table("payables");
  frm.refresh_field("payables");

  frm.set_value("total_payable_amount", 0);

  systemIsFilling = false;
}


// ======================================================
// Child table events
// ======================================================
frappe.ui.form.on(CHILD_TABLE, {

  day_count(frm, cdt, cdn) {
    if (systemIsFilling) return;
    recalc_row(frm, cdt, cdn);
  },

  rate_per_day(frm, cdt, cdn) {
    if (systemIsFilling) return;
    recalc_row(frm, cdt, cdn);
  },

  amount(frm) {
    if (systemIsFilling) return;
    update_total(frm);
  }
});


// ======================================================
// إعادة حساب الصف
// ======================================================
function recalc_row(frm, cdt, cdn) {

  let row = locals[cdt][cdn];

  let days = flt(row.day_count || 0);
  let rate = flt(row.rate_per_day || 0);

  let amount = days * rate;

  frappe.model.set_value(cdt, cdn, "amount", amount);

  update_total(frm);
}


// ======================================================
// تحديث التوتل من الجدول
// ======================================================
function update_total(frm) {

  let total = 0;

  (frm.doc.payables || []).forEach(r => {
    total = total + flt(r.amount || 0);
  });

  frm.set_value("total_payable_amount", total);
}