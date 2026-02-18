import frappe
import calendar

from datetime import date, timedelta
from frappe.utils import getdate, nowdate, flt
from dateutil.relativedelta import relativedelta


# =========================================================
# نجيب آخر Salary Structure Assignment للموظف
# =========================================================
def get_active_salary_structure_assignment(employee_id, reference_date):

    assignment_name = frappe.db.get_value(
        "Salary Structure Assignment",
        {
            "employee": employee_id,
            "docstatus": 1,
            "from_date": ("<=", reference_date)
        },
        "name",
        order_by="from_date desc"
    )

    if assignment_name:
        return frappe.get_doc("Salary Structure Assignment", assignment_name)

    return None


# =========================================================
# نحضر context للفورمولات (base + custom_total + أي رقم ثاني)
# =========================================================
def build_salary_formula_context(assignment_doc):

    context = {}

    try:
        assignment_dict = assignment_doc.as_dict()
    except Exception:
        assignment_dict = {}

    context["base"] = flt(getattr(assignment_doc, "base", 0) or 0)
    context["custom_total"] = flt(getattr(assignment_doc, "custom_total", 0) or 0)

    for field_name in assignment_dict:
        field_value = assignment_dict.get(field_name)
        if isinstance(field_value, (int, float)):
            context[field_name] = flt(field_value)

    return context


# =========================================================
# نحسب أي formula بطريقة آمنة
# =========================================================
def safe_eval_formula(formula_text, context):

    if not formula_text:
        return 0

    try:
        return flt(frappe.safe_eval(formula_text, None, context))
    except Exception:
        return 0


# =========================================================
# نجمع earnings من Salary Structure
# =========================================================
def sum_salary_structure_earnings(salary_structure_name, assignment_doc):

    try:
        salary_structure_doc = frappe.get_doc("Salary Structure", salary_structure_name)
    except Exception:
        return 0

    context = build_salary_formula_context(assignment_doc)

    total = 0

    if salary_structure_doc.earnings:
        for row in salary_structure_doc.earnings:

            amount = flt(getattr(row, "amount", 0) or 0)
            formula = (getattr(row, "formula", "") or "").strip()

            if amount:
                total = total + amount
            elif formula:
                total = total + safe_eval_formula(formula, context)

    return flt(total)


# =========================================================
# الراتب الشهري النهائي
# =========================================================
def get_monthly_salary(assignment_doc):

    if not assignment_doc:
        return 0

    salary_structure = getattr(assignment_doc, "salary_structure", None)

    if salary_structure:
        from_structure = sum_salary_structure_earnings(salary_structure, assignment_doc)
        if from_structure:
            return from_structure

    custom_total = flt(getattr(assignment_doc, "custom_total", 0) or 0)
    base = flt(getattr(assignment_doc, "base", 0) or 0)

    if custom_total:
        return custom_total

    return base


# =========================================================
# تواريخ
# =========================================================
def first_day_of_month(d):
    return date(d.year, d.month, 1)

def days_in_month(d):
    return calendar.monthrange(d.year, d.month)[1]

def last_day_of_month(d):
    return date(d.year, d.month, days_in_month(d))

def is_end_of_month(d):
    return d.day == days_in_month(d)

def inclusive_days(start_date, end_date):

    if not start_date or not end_date:
        return 0

    if end_date < start_date:
        return 0

    return (end_date - start_date).days + 1


# =========================================================
# نقرر تاريخ الحساب
# =========================================================
def get_calc_date(employee_id, transaction_date=None):

    if transaction_date:
        return getdate(transaction_date)

    relieving_date = frappe.db.get_value("Employee", employee_id, "relieving_date")

    if relieving_date:
        return getdate(relieving_date)

    return getdate(nowdate())


# =========================================================
# آخر Salary Slip
# =========================================================
def get_last_salary_slip(employee_id):

    slip_name = frappe.db.get_value(
        "Salary Slip",
        {
            "employee": employee_id,
            "docstatus": 1
        },
        "name",
        order_by="end_date desc"
    )

    if slip_name:
        return frappe.get_doc("Salary Slip", slip_name)

    return None


# =========================================================
# تحقق من حالة الموظف
# =========================================================
@frappe.whitelist()
def validate_employee(employee):

    emp = frappe.db.get_value(
        "Employee",
        employee,
        ["status", "relieving_date"],
        as_dict=True
    )

    if not emp:
        return {"ok": False, "msg": "الموظف مش موجود"}

    if not emp.relieving_date:
        return {"ok": False, "msg": "لازم تحط Relieving Date"}

    if (emp.status or "").lower() == "active":
        return {"ok": False, "msg": "الموظف لسه Active"}

    return {"ok": True}


# =========================================================
# حساب أيام العمل
# =========================================================
def get_worked_days(employee_id, calc_date):

    assignment = get_active_salary_structure_assignment(employee_id, calc_date)

    if not assignment:
        return {"ok": False, "msg": "ما في Salary Structure Assignment"}

    monthly_salary = get_monthly_salary(assignment)

    rate_per_day = flt(monthly_salary / 30)

    month_start = first_day_of_month(calc_date)

    doj = frappe.db.get_value("Employee", employee_id, "date_of_joining")
    doj = getdate(doj) if doj else None

    candidates = [month_start]

    if doj and doj > month_start:
        candidates.append(doj)

    last_slip = get_last_salary_slip(employee_id)

    if last_slip and last_slip.end_date:
        after_slip = getdate(last_slip.end_date) + timedelta(days=1)
        if after_slip > month_start:
            candidates.append(after_slip)

    period_from = max(candidates)
    period_to = calc_date

    worked_days = inclusive_days(period_from, period_to)

    if is_end_of_month(period_to):
        amount = monthly_salary
        worked_days_display = 30
    else:
        amount = worked_days * rate_per_day
        worked_days_display = worked_days

    return {
        "ok": True,
        "worked_days": worked_days_display,
        "rate_per_day": rate_per_day,
        "amount": amount
    }


# =========================================================
# حساب الإجازات اليومية (28/30/31)
# =========================================================
def calculate_daily_accrual(start_date, end_date, annual_days):

    monthly = flt(annual_days / 12)
    total = 0

    current = start_date

    while current <= end_date:

        month_end = last_day_of_month(current)

        segment_end = end_date
        if month_end < end_date:
            segment_end = month_end

        worked = inclusive_days(current, segment_end)
        dim = days_in_month(current)

        if current.day == 1 and segment_end == month_end:
            total = total + monthly
        else:
            total = total + (monthly / dim) * worked

        current = segment_end + timedelta(days=1)

    return total


# =========================================================
# Full & Final Payload
# =========================================================
@frappe.whitelist()
def get_full_and_final_payload(employee, transaction_date=None):

    check = validate_employee(employee)
    if not check["ok"]:
        return check

    calc_date = get_calc_date(employee, transaction_date)

    worked = get_worked_days(employee, calc_date)
    if not worked["ok"]:
        return worked

    doj = frappe.db.get_value("Employee", employee, "date_of_joining")
    doj = getdate(doj)

    # افترض السنوي 21 (تقدر تربطه بالسيستم لاحقاً)
    annual_leave = 21

    accrued_leave = calculate_daily_accrual(doj, calc_date, annual_leave)

    leave_amount = accrued_leave * worked["rate_per_day"]

    payables = []

    payables.append({
        "component": "Worked Day",
        "day_count": worked["worked_days"],
        "rate_per_day": worked["rate_per_day"],
        "amount": worked["amount"]
    })

    payables.append({
        "component": "Leave Encashment",
        "day_count": accrued_leave,
        "rate_per_day": worked["rate_per_day"],
        "amount": leave_amount
    })

    total = worked["amount"] + leave_amount

    return {
        "ok": True,
        "payables": payables,
        "totals": {
            "total_payable": total
        }
    }