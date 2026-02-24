# =========================================================
# Full & Final - One File Version (Beginner Friendly)
# - كل شيء في ملف واحد (عشان ما يصير import مشاكل)
# - الكومنتات عربي (للدراسة)
# - رسائل الأخطاء إنجليزي (حسب طلبك)
#
# Business Logic:
# 1) calc_date = min(transaction_date, relieving_date)
# 2) Worked Days:
#    period_from = max(month_start, doj, after_last_slip)
#    period_to   = calc_date
#    rate_per_day = monthly_salary / 30
#    if end_of_month and period_from == month_start => pay full month (30)
# 3) Leave Encashment (Annual only):
#    available = (total_leaves_allocated + extra_days) - (annual_taken + personal_taken)
#    داخل فترة الـ allocation نفسها
#    personal types: اسمها يحتوي "Personal"
# 4) Service:
#    years/months/days + total_years = total_days/365
# 5) Currency:
#    company_currency = Employee.company -> Company.default_currency
# =========================================================

import frappe
from datetime import date, timedelta
from frappe.utils import getdate, nowdate, flt


# =========================================================
# (A) Date Helpers
# =========================================================
def days_inclusive(from_date, to_date):
    """عدد الأيام بين تاريخين شاملين."""
    if not from_date or not to_date:
        return 0
    if to_date < from_date:
        return 0
    return (to_date - from_date).days + 1


def is_end_of_month(d):
    """هل التاريخ آخر يوم بالشهر؟"""
    return (d + timedelta(days=1)).month != d.month


def month_start_date(d):
    """أول يوم بالشهر"""
    return date(d.year, d.month, 1)


# =========================================================
# (B) Employee Helpers
# =========================================================
def validate_employee(employee):
    """
    يتحقق:
    - الموظف موجود
    - لديه relieving_date
    - ليس Active
    """
    emp = frappe.db.get_value(
        "Employee",
        employee,
        ["status", "relieving_date"],
        as_dict=True
    )

    if not emp:
        return {"ok": False, "msg": "Employee not found."}

    if not emp.relieving_date:
        return {"ok": False, "msg": "Relieving Date is required."}

    if (emp.status or "").lower() == "active":
        return {"ok": False, "msg": "Employee is still Active."}

    return {"ok": True}


def get_calc_date(employee, transaction_date=None):
    """
    Full & Final:
    calc_date لا يجوز يكون بعد relieving_date
    calc_date = min(transaction_date, relieving_date)
    """
    relieving_date = frappe.db.get_value("Employee", employee, "relieving_date")
    relieving_date = getdate(relieving_date) if relieving_date else None

    trx = getdate(transaction_date) if transaction_date else None

    if relieving_date and trx:
        return min(trx, relieving_date)

    if relieving_date:
        return relieving_date

    if trx:
        return trx

    return getdate(nowdate())


def get_employee_doj(employee):
    """تاريخ الانضمام DOJ"""
    doj = frappe.db.get_value("Employee", employee, "date_of_joining")
    return getdate(doj) if doj else None


def get_employee_company_currency(employee):
    """
    يرجّع عملة الشركة الافتراضية للموظف:
    Employee.company -> Company.default_currency
    """
    company = frappe.db.get_value("Employee", employee, "company")
    if not company:
        return None
    return frappe.db.get_value("Company", company, "default_currency")


# =========================================================
# (C) Salary Helpers
# =========================================================
def get_salary_assignment(employee, as_of_date):
    """آخر Salary Structure Assignment (Submitted) فعال بتاريخ معين."""
    name = frappe.db.get_value(
        "Salary Structure Assignment",
        {
            "employee": employee,
            "docstatus": 1,
            "from_date": ("<=", as_of_date),
        },
        "name",
        order_by="from_date desc"
    )
    return frappe.get_doc("Salary Structure Assignment", name) if name else None


def get_monthly_salary_from_assignment(assignment):
    """
    طريقة مبسطة:
    - custom_total إذا موجود
    - وإلا base
    """
    custom_total = flt(getattr(assignment, "custom_total", 0) or 0)
    base = flt(getattr(assignment, "base", 0) or 0)
    return custom_total if custom_total else base


def get_last_salary_slip_end(employee):
    """آخر end_date من Salary Slip (Submitted)."""
    end_date_value = frappe.db.get_value(
        "Salary Slip",
        {"employee": employee, "docstatus": 1},
        "end_date",
        order_by="end_date desc"
    )
    return getdate(end_date_value) if end_date_value else None


def calculate_worked_days(employee, calc_date):
    """
    حساب Worked Days (يغطي كل الحالات):
    period_from = max(
        month_start,
        DOJ (لو انضم بنص الشهر),
        after_last_slip (لو موجود)
    )
    period_to = calc_date
    """
    assignment = get_salary_assignment(employee, calc_date)
    if not assignment:
        return None, "No Salary Structure Assignment found."

    monthly_salary = get_monthly_salary_from_assignment(assignment)
    rate_per_day = flt(monthly_salary / 30)

    month_start = month_start_date(calc_date)
    doj = get_employee_doj(employee)
    last_slip_end = get_last_salary_slip_end(employee)

    candidates = [month_start]

    if doj:
        candidates.append(doj)

    if last_slip_end:
        candidates.append(last_slip_end + timedelta(days=1))

    period_from = max(candidates)
    period_to = calc_date

    worked_days = days_inclusive(period_from, period_to)

    # شهر كامل فقط إذا بدأنا من أول الشهر
    if is_end_of_month(period_to) and period_from == month_start:
        return {
            "worked_days": 30,
            "rate_per_day": rate_per_day,
            "amount": monthly_salary,
            "assignment_name": assignment.name,
            "period_from": str(period_from),
            "period_to": str(period_to),
        }, None

    return {
        "worked_days": worked_days,
        "rate_per_day": rate_per_day,
        "amount": flt(worked_days * rate_per_day),
        "assignment_name": assignment.name,
        "period_from": str(period_from),
        "period_to": str(period_to),
    }, None


# =========================================================
# (D) Leave Helpers (No manual SQL)
# =========================================================
def get_leave_types_by_keyword(keyword):
    """يجلب Leave Types اللي اسمها يحتوي كلمة معينة."""
    return frappe.get_all(
        "Leave Type",
        filters={"name": ["like", f"%{keyword}%"]},
        pluck="name"
    ) or []


def get_leave_allocation(employee, leave_type, calc_date):
    """
    Leave Allocation (Submitted) يغطي calc_date:
    from_date <= calc_date <= to_date
    """
    name = frappe.db.get_value(
        "Leave Allocation",
        {
            "employee": employee,
            "leave_type": leave_type,
            "docstatus": 1,
            "from_date": ("<=", calc_date),
            "to_date": (">=", calc_date),
        },
        "name",
        order_by="from_date desc"
    )
    return frappe.get_doc("Leave Allocation", name) if name else None


def get_allocation_total_days(allocation_doc):
    """
    total allocation = total_leaves_allocated + extra_days
    (extra_days اسم الحقل عندك)
    """
    allocated = flt(getattr(allocation_doc, "total_leaves_allocated", 0) or 0)
    extra = flt(getattr(allocation_doc, "extra_days", 0) or 0)
    return flt(allocated + extra)


def get_taken_leave_days(employee, leave_types, from_date, to_date):
    """
    مجموع total_leave_days من Leave Application ضمن الفترة
    بشرط Approved + Submitted
    """
    if not leave_types:
        return 0

    rows = frappe.get_all(
        "Leave Application",
        filters={
            "employee": employee,
            "docstatus": 1,
            "status": "Approved",
            "leave_type": ["in", leave_types],
            "from_date": [">=", from_date],
            "to_date": ["<=", to_date],
        },
        fields=["sum(total_leave_days) as total"]
    )

    total = 0
    if rows and rows[0] and rows[0].get("total") is not None:
        total = rows[0].get("total")

    return flt(total or 0)


def calculate_annual_leave_available(employee, calc_date):
    """
    Annual Leave Encashment:
    available = (allocated + extra_days) - (annual_taken + personal_taken)
    """
    annual_types = get_leave_types_by_keyword("Annual")
    personal_types = get_leave_types_by_keyword("Personal")

    if not annual_types:
        return {"available_days": 0, "allocation_name": None}

    total_available = 0
    reference_allocation_name = None

    for annual_type in annual_types:
        allocation = get_leave_allocation(employee, annual_type, calc_date)
        if not allocation:
            continue

        if not reference_allocation_name:
            reference_allocation_name = allocation.name

        alloc_total = get_allocation_total_days(allocation)

        period_from = getdate(allocation.from_date)
        period_to = getdate(allocation.to_date)

        annual_taken = get_taken_leave_days(employee, [annual_type], period_from, period_to)
        personal_taken = get_taken_leave_days(employee, personal_types, period_from, period_to)

        available = flt(alloc_total - (annual_taken + personal_taken))
        if available < 0:
            available = 0

        total_available += available

    return {
        "available_days": flt(total_available),
        "allocation_name": reference_allocation_name
    }


# =========================================================
# (E) Service Helpers
# =========================================================
def calculate_service(doj, calc_date):
    """
    حساب مدة الخدمة:
    - years / months / days
    - total_years = total_days / 365
    """
    if not doj or not calc_date:
        return {"years": 0, "months": 0, "days": 0, "total_years": 0.0}

    doj = getdate(doj)
    calc_date = getdate(calc_date)

    if calc_date < doj:
        return {"years": 0, "months": 0, "days": 0, "total_years": 0.0}

    total_days = days_inclusive(doj, calc_date)
    total_years = flt(total_days / 365)

    years = 0
    months = 0
    cursor = doj

    # عد سنوات كاملة
    while True:
        try:
            next_year = date(cursor.year + 1, cursor.month, cursor.day)
        except ValueError:
            next_year = date(cursor.year + 1, 2, 28)

        if next_year <= calc_date:
            years += 1
            cursor = next_year
        else:
            break

    # عد أشهر كاملة
    while True:
        if cursor.month == 12:
            ny, nm = cursor.year + 1, 1
        else:
            ny, nm = cursor.year, cursor.month + 1

        try:
            next_month = date(ny, nm, cursor.day)
        except ValueError:
            # clamp لآخر يوم بالشهر
            if nm == 12:
                month_end = date(ny + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(ny, nm + 1, 1) - timedelta(days=1)
            next_month = month_end

        if next_month <= calc_date:
            months += 1
            cursor = next_month
        else:
            break

    days = (calc_date - cursor).days

    return {
        "years": int(years),
        "months": int(months),
        "days": int(days),
        "total_years": flt(total_years),
    }


# =========================================================
# (F) API Endpoint
# =========================================================
@frappe.whitelist()
def get_full_and_final_payload(employee, transaction_date=None):
    """
    الدالة اللي بنستدعيها من الجافا
    """
    check = validate_employee(employee)
    if not check["ok"]:
        return check

    calc_date = get_calc_date(employee, transaction_date)

    worked_data, error = calculate_worked_days(employee, calc_date)
    if error:
        return {"ok": False, "msg": error}

    leave_info = calculate_annual_leave_available(employee, calc_date)
    leave_days = flt(leave_info.get("available_days") or 0)
    leave_amount = flt(leave_days * worked_data["rate_per_day"])

    doj = get_employee_doj(employee)
    service = calculate_service(doj, calc_date)

    payables = []

    # Worked Day
    payables.append({
        "component": "Worked Day",
        "day_count": worked_data["worked_days"],
        "rate_per_day": worked_data["rate_per_day"],
        "amount": worked_data["amount"],
        "reference_document_type": "Salary Structure Assignment",
        "reference_document": worked_data.get("assignment_name"),
    })

    # Leave Encashment
    payables.append({
        "component": "Leave Encashment",
        "day_count": leave_days,
        "rate_per_day": worked_data["rate_per_day"],
        "amount": leave_amount,
        "reference_document_type": "Leave Allocation",
        "reference_document": leave_info.get("allocation_name"),
    })

    total = flt(worked_data["amount"] + leave_amount)

    # ✅ Currency: from employee.company -> company.default_currency
    company_currency = get_employee_company_currency(employee)

    return {
        "ok": True,
        "company_currency": company_currency,

        "payables": payables,
        "totals": {"total_payable": total},

        # Service fields
        "service_years": service["years"],
        "service_months": service["months"],
        "service_days": service["days"],
        "total_years": service["total_years"],

        # Debug (مفيد للاختبار)
        "debug_calc_date": str(calc_date),
        "debug_worked_from": worked_data.get("period_from"),
        "debug_worked_to": worked_data.get("period_to"),
    }