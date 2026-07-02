"""
Unit tests for src/clean.py. These run against small hand-built DataFrames,
not the real CSV -- the point is to pin down each cleaning rule's behavior
on edge cases (nulls, invalid values, boundary conditions) independent of
whatever happens to be in the actual dataset.
"""

import pandas as pd
import pytest

from src import clean


def test_split_department_region_basic():
    df = pd.DataFrame({"Department_Region": ["Cloud Tech-Florida", "HR-Texas"]})
    out = clean.split_department_region(df)
    assert out["department_name"].tolist() == ["Cloud Tech", "HR"]
    assert out["region_name"].tolist() == ["Florida", "Texas"]


def test_clean_age_drops_out_of_range_values():
    df = pd.DataFrame({"Age": [25, 5, 150, None, 40]})
    out = clean.clean_age(df)
    # 5 and 150 are outside MIN_VALID_AGE/MAX_VALID_AGE and should become NA, not be clipped
    assert out["Age"].isna().tolist() == [False, True, True, True, False]
    assert out["Age"].dropna().tolist() == [25, 40]


def test_clean_salary_negative_becomes_null():
    df = pd.DataFrame({"Salary": [50000.0, -1000.0, None]})
    out = clean.clean_salary(df)
    assert out["Salary"].isna().tolist() == [False, True, True]
    assert out["Salary"].iloc[0] == 50000.0


def test_clean_phone_valid_ten_digit_is_formatted():
    df = pd.DataFrame({"Phone": [-5551234567]})
    out = clean.clean_phone(df)
    assert out["Phone"].iloc[0] == "(555) 123-4567"


def test_clean_phone_invalid_length_becomes_null():
    df = pd.DataFrame({"Phone": [-551234, -55512345678]})  # 6 digits, 11 digits
    out = clean.clean_phone(df)
    assert out["Phone"].isna().all()


def test_clean_join_date_parses_valid_and_nulls_invalid():
    df = pd.DataFrame({"Join_Date": ["1/15/2023", "not-a-date"]})
    out = clean.clean_join_date(df)
    assert out["Join_Date"].iloc[0] == pd.Timestamp("2023-01-15")
    assert pd.isna(out["Join_Date"].iloc[1])


def test_clean_status_rejects_unknown_values():
    df = pd.DataFrame({"Status": [" active ", "Bogus", "PENDING"]})
    out = clean.clean_status(df)
    assert out["Status"].iloc[0] == "Active"
    assert pd.isna(out["Status"].iloc[1])
    assert out["Status"].iloc[2] == "Pending"


def test_build_performance_dim_has_expected_rank_order():
    dim = clean.build_performance_dim()
    ranked = dict(zip(dim["label"], dim["rank"]))
    assert ranked["Poor"] < ranked["Average"] < ranked["Good"] < ranked["Excellent"]


def test_build_departments_dim_dedupes_and_sorts():
    df = pd.DataFrame({"department_name": ["HR", "Sales", "HR", "Admin"]})
    dim = clean.build_departments_dim(df)
    assert dim["department_name"].tolist() == ["Admin", "HR", "Sales"]
    assert dim["department_id"].tolist() == [1, 2, 3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
