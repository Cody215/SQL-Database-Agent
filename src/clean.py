"""
Pure data-cleaning functions for the employee dataset.

Deliberately has no file or database I/O in this module -- every function takes
a DataFrame (or column) in and returns a cleaned one out. That makes each rule
independently unit-testable (see tests/test_clean.py) without needing a real CSV
or a database connection.

Design decision worth calling out: where the source data is genuinely invalid
(e.g. a phone number with the wrong digit count) we set the value to NULL rather
than guessing or fabricating a "fixed" value. Inventing data is worse than
admitting it's missing -- a NULL is honest, a guessed value is silent corruption.
"""

import pandas as pd

PERFORMANCE_RANK = {
    "Poor": 1,
    "Average": 2,
    "Good": 3,
    "Excellent": 4,
}

VALID_STATUSES = {"Active", "Inactive", "Pending"}

# Plausible bounds for a working-age employee. Anything outside this is treated
# as a data error rather than a real value.
MIN_VALID_AGE = 16
MAX_VALID_AGE = 80


def clean_names(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace and normalize casing on first/last name."""
    df = df.copy()
    df["First_Name"] = df["First_Name"].str.strip().str.title()
    df["Last_Name"] = df["Last_Name"].str.strip().str.title()
    return df


def split_department_region(df: pd.DataFrame) -> pd.DataFrame:
    """
    Split the combined 'Department_Region' field (e.g. 'Cloud Tech-Florida')
    into two separate columns. Uses rsplit on the LAST '-' specifically because
    department names themselves can contain a space but not a hyphen, while
    region names here are always a single token -- this avoids mis-splitting
    a department name that happens to contain extra words.
    """
    df = df.copy()
    split = df["Department_Region"].str.rsplit("-", n=1, expand=True)
    df["department_name"] = split[0].str.strip()
    df["region_name"] = split[1].str.strip()
    return df.drop(columns=["Department_Region"])


def clean_age(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cast Age to a nullable integer type. Values outside a plausible working-age
    range are treated as data errors and set to NULL rather than clipped --
    clipping would silently misrepresent who that row actually is.
    """
    df = df.copy()
    age = pd.to_numeric(df["Age"], errors="coerce")
    age = age.where(age.between(MIN_VALID_AGE, MAX_VALID_AGE))
    df["Age"] = age.astype("Int64")
    return df


def clean_salary(df: pd.DataFrame) -> pd.DataFrame:
    """Round salary to cents; negative salaries (data errors) become NULL."""
    df = df.copy()
    salary = pd.to_numeric(df["Salary"], errors="coerce")
    salary = salary.where(salary >= 0)
    df["Salary"] = salary.round(2)
    return df


def clean_email(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase and strip email addresses for consistent matching/joins."""
    df = df.copy()
    df["Email"] = df["Email"].str.strip().str.lower()
    return df


def clean_phone(df: pd.DataFrame) -> pd.DataFrame:
    """
    The source phone numbers are corrupted: stored as signed integers with
    inconsistent digit counts (7-10 digits). A phone number's sign carries no
    meaning, so we take the absolute value, but a 7-8 digit number is missing
    real digits -- there's no way to recover what they should have been, so
    those become NULL instead of being padded with guessed digits. Only
    10-digit values are formatted into a standard (XXX) XXX-XXXX display form.
    """
    df = df.copy()
    digits = df["Phone"].abs().astype("Int64").astype(str)

    def format_if_valid(d: str):
        if len(d) == 10 and d.isdigit():
            return f"({d[0:3]}) {d[3:6]}-{d[6:10]}"
        return None

    df["Phone"] = digits.map(format_if_valid)
    return df


def clean_join_date(df: pd.DataFrame) -> pd.DataFrame:
    """Parse the M/D/YYYY string into a real date type. Unparseable -> NaT."""
    df = df.copy()
    df["Join_Date"] = pd.to_datetime(df["Join_Date"], format="%m/%d/%Y", errors="coerce")
    return df


def clean_status(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize casing/whitespace; anything outside the known set becomes NULL."""
    df = df.copy()
    status = df["Status"].str.strip().str.title()
    df["Status"] = status.where(status.isin(VALID_STATUSES))
    return df


def clean_performance_score(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize casing/whitespace on the performance label."""
    df = df.copy()
    df["Performance_Score"] = df["Performance_Score"].str.strip().str.title()
    return df


def clean_remote_work(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure Remote_Work is a proper boolean (handles 'TRUE'/'FALSE' strings too)."""
    df = df.copy()
    if df["Remote_Work"].dtype != bool:
        df["Remote_Work"] = (
            df["Remote_Work"].astype(str).str.strip().str.lower().map({"true": True, "false": False})
        )
    return df


def clean_employee_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace on the natural key used as the primary key downstream."""
    df = df.copy()
    df["Employee_ID"] = df["Employee_ID"].str.strip()
    return df


def run_all_cleaning(df: pd.DataFrame) -> pd.DataFrame:
    """Apply every column-level cleaning rule in sequence."""
    df = clean_employee_ids(df)
    df = clean_names(df)
    df = split_department_region(df)
    df = clean_age(df)
    df = clean_salary(df)
    df = clean_email(df)
    df = clean_phone(df)
    df = clean_join_date(df)
    df = clean_status(df)
    df = clean_performance_score(df)
    df = clean_remote_work(df)
    return df


def build_departments_dim(df: pd.DataFrame) -> pd.DataFrame:
    """One row per distinct department, with a surrogate integer key."""
    names = sorted(df["department_name"].dropna().unique())
    return pd.DataFrame({"department_id": range(1, len(names) + 1), "department_name": names})


def build_regions_dim(df: pd.DataFrame) -> pd.DataFrame:
    """One row per distinct region, with a surrogate integer key."""
    names = sorted(df["region_name"].dropna().unique())
    return pd.DataFrame({"region_id": range(1, len(names) + 1), "region_name": names})


def build_performance_dim() -> pd.DataFrame:
    """
    Performance levels are a fixed, known set (not derived from the data) so
    that 'rank' has a stable, intentional ordering rather than whatever order
    happens to appear in a given CSV.
    """
    return pd.DataFrame(
        [{"performance_id": i, "label": label, "rank": rank} for i, (label, rank) in enumerate(PERFORMANCE_RANK.items(), start=1)]
    )


def build_employees_fact(
    df: pd.DataFrame,
    departments_dim: pd.DataFrame,
    regions_dim: pd.DataFrame,
    performance_dim: pd.DataFrame,
) -> pd.DataFrame:
    """
    Join the cleaned flat dataframe against the dimension tables to attach
    surrogate foreign keys, then select/rename into the final employees shape.
    """
    df = df.merge(departments_dim, on="department_name", how="left")
    df = df.merge(regions_dim, on="region_name", how="left")
    df = df.merge(
        performance_dim.rename(columns={"label": "Performance_Score"}),
        on="Performance_Score",
        how="left",
    )

    out = df.rename(
        columns={
            "Employee_ID": "employee_id",
            "First_Name": "first_name",
            "Last_Name": "last_name",
            "Age": "age",
            "Email": "email",
            "Phone": "phone",
            "Join_Date": "join_date",
            "Status": "status",
            "Remote_Work": "remote_work",
            "Salary": "salary",
        }
    )

    return out[
        [
            "employee_id",
            "first_name",
            "last_name",
            "age",
            "email",
            "phone",
            "join_date",
            "status",
            "remote_work",
            "salary",
            "department_id",
            "region_id",
            "performance_id",
        ]
    ]
