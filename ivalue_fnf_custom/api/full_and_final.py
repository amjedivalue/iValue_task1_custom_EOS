import frappe
from datetime import date, timedelta
from frappe.utils import getdate, nowdate, flt


# =========================================================
# DATE HELPERS
# =========================================================

def count_days(from_date, to_date):
    if not from_date or not to_date or to_date < from_date:
        return 0
    return (to_date - from_date).days + 1


def is_last_day_of_month(d):
    return (d + timedelta(days=1)).month != d.month


def first_day_of_month(d):
    return date(d.year, d.month, 1)


# =========================================================
# EMPLOYEE HELPERS
# =========================================================

def check_employee(employee):
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
        return {"ok": False, "msg": "Employee still Active."}

    return {"ok": True}


def get_final_date(employee):
    relieving = frappe.db.get_value("Employee", employee, "relieving_date")
    return getdate(relieving)


def get_join_date(employee):
    doj = frappe.db.get_value("Employee", employee, "date_of_joining")
    return getdate(doj) if doj else None


def get_company_currency(employee):
    company = frappe.db.get_value("Employee", employee, "company")
    return frappe.db.get_value("Company", company, "default_currency") if company else None


# =========================================================
# SALARY HELPERS
# =========================================================

def get_salary_assignment(employee, on_date):
    name = frappe.db.get_value(
        "Salary Structure Assignment",
        {
            "employee": employee,
            "docstatus": 1,
            "from_date": ("<=", on_date),
        },
        "name",
        order_by="from_date desc"
    )

    return frappe.get_doc("Salary Structure Assignment", name) if name else None


def get_month_salary(assignment):
    custom_total = flt(getattr(assignment, "custom_total", 0))
    base = flt(getattr(assignment, "base", 0))
    return custom_total if custom_total else base


def get_last_salary_slip(employee):
    last_end = frappe.db.get_value(
        "Salary Slip",
        {"employee": employee, "docstatus": 1},
        "end_date",
        order_by="end_date desc"
    )
    return getdate(last_end) if last_end else None


def calculate_work_period(employee, final_date):

    salary_assignment = get_salary_assignment(employee, final_date)
    if not salary_assignment:
        return None, "No Salary Structure Assignment."

    monthly_salary = get_month_salary(salary_assignment)
    daily_rate = flt(monthly_salary / 30)

    month_start = first_day_of_month(final_date)
    join_date = get_join_date(employee)
    last_slip = get_last_salary_slip(employee)

    start_candidates = [month_start]

    if join_date:
        start_candidates.append(join_date)

    if last_slip:
        start_candidates.append(last_slip + timedelta(days=1))

    period_start = max(start_candidates)
    period_end = final_date

    worked_days = count_days(period_start, period_end)

    if is_last_day_of_month(period_end) and period_start == month_start:
        return {
            "days": 30,
            "rate": daily_rate,
            "amount": monthly_salary,
            "assignment": salary_assignment.name,
            "from": str(period_start),
            "to": str(period_end),
        }, None

    return {
        "days": worked_days,
        "rate": daily_rate,
        "amount": flt(worked_days * daily_rate),
        "assignment": salary_assignment.name,
        "from": str(period_start),
        "to": str(period_end),
    }, None


# =========================================================
# LEAVE HELPERS
# =========================================================

def find_leave_types(keyword):
    return frappe.get_all(
        "Leave Type",
        filters={"name": ["like", f"%{keyword}%"]},
        pluck="name"
    ) or []


def get_leave_allocation(employee, leave_type, final_date):
    name = frappe.db.get_value(
        "Leave Allocation",
        {
            "employee": employee,
            "leave_type": leave_type,
            "docstatus": 1,
            "from_date": ("<=", final_date),
            "to_date": (">=", final_date),
        },
        "name",
        order_by="from_date desc"
    )

    return frappe.get_doc("Leave Allocation", name) if name else None


def get_allocation_days(allocation):
    allocated = flt(getattr(allocation, "total_leaves_allocated", 0))
    extra = flt(getattr(allocation, "extra_days", 0))
    return allocated + extra


def get_taken_leaves(employee, leave_types, from_date, to_date):

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

    return flt(rows[0].total or 0) if rows else 0


def calculate_remaining_annual_leave(employee, final_date):

    annual_types = find_leave_types("Annual")
    personal_types = find_leave_types("Personal")

    total_remaining = 0
    allocation_ref = None

    for annual in annual_types:

        allocation = get_leave_allocation(employee, annual, final_date)
        if not allocation:
            continue

        if not allocation_ref:
            allocation_ref = allocation.name

        allocated_days = get_allocation_days(allocation)

        period_from = getdate(allocation.from_date)
        period_to = getdate(allocation.to_date)

        annual_used = get_taken_leaves(employee, [annual], period_from, period_to)
        personal_used = get_taken_leaves(employee, personal_types, period_from, period_to)

        remaining = allocated_days - (annual_used + personal_used)
        total_remaining += max(remaining, 0)

    return {
        "remaining_days": flt(total_remaining),
        "allocation": allocation_ref
    }


# =========================================================
# SERVICE
# =========================================================

def calculate_service_period(join_date, final_date):

    if not join_date:
        return {"years": 0, "months": 0, "days": 0, "total_years": 0}

    total_days = count_days(join_date, final_date)
    total_years = flt(total_days / 365)

    return {
        "years": int(total_days // 365),
        "months": 0,
        "days": int(total_days % 365),
        "total_years": total_years,
    }


# =========================================================
# MAIN API
# =========================================================

@frappe.whitelist()
def get_full_and_final_payload(employee, transaction_date=None):

    validation = check_employee(employee)
    if not validation["ok"]:
        return validation

    final_date = get_final_date(employee)

    work_info, error = calculate_work_period(employee, final_date)
    if error:
        return {"ok": False, "msg": error}

    leave_info = calculate_remaining_annual_leave(employee, final_date)

    leave_days = leave_info["remaining_days"]
    leave_amount = leave_days * work_info["rate"]

    service = calculate_service_period(get_join_date(employee), final_date)

    payables = [
        {
            "component": "Worked Day",
            "day_count": work_info["days"],
            "rate_per_day": work_info["rate"],
            "amount": work_info["amount"],
            "reference_document": work_info["assignment"],
        },
        {
            "component": "Leave Encashment",
            "day_count": leave_days,
            "rate_per_day": work_info["rate"],
            "amount": leave_amount,
            "reference_document": leave_info["allocation"],
        }
    ]

    total = work_info["amount"] + leave_amount

    return {
        "ok": True,
        "company_currency": get_company_currency(employee),
        "payables": payables,
        "totals": {"total_payable": total},
        "service_years": service["years"],
        "service_months": service["months"],
        "service_days": service["days"],
        "total_years": service["total_years"],
        "debug_final_date": str(final_date),
        "debug_from": work_info["from"],
        "debug_to": work_info["to"],
    }