"""
Orchestrator: connects the ETL pipeline to the database.

Usage:
    python main.py
    python main.py --csv data/raw/Messy_Employee_dataset.csv
"""

import argparse
import json

from src import pipeline
from src.db import get_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the employee ETL pipeline.")
    parser.add_argument(
        "--csv",
        default="data/raw/Messy_Employee_dataset.csv",
        help="Path to the raw CSV file (default: data/raw/Messy_Employee_dataset.csv)",
    )
    args = parser.parse_args()

    engine = get_engine("ETL_DATABASE_URL")
    report = pipeline.run(args.csv, engine)

    print("\nETL run complete. Data quality report:")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
