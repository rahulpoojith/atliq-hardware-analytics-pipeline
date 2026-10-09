"""Read a small customer sample from the AtliQ SQL Server database."""

import os

import pandas as pd
import pyodbc


def brace_odbc_value(value: str) -> str:
    """Wrap an ODBC value and escape closing braces inside it."""
    return "{" + value.replace("}", "}}") + "}"


def main() -> None:
    password = os.environ.get("ATLIQ_SQL_PASSWORD")
    if not password:
        raise RuntimeError(
            "Set the ATLIQ_SQL_PASSWORD environment variable in this terminal first."
        )

    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=10.211.55.4,53500;"
        "DATABASE=AtliqHardware;"
        "UID=Igris;"
        f"PWD={brace_odbc_value(password)};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )

    query = """
        SELECT TOP (5) customer_code, customer, market
        FROM dbo.dim_customer
        ORDER BY customer_code;
    """

    with pyodbc.connect(connection_string) as connection:
        cursor = connection.cursor()
        cursor.execute(query)
        column_names = [column[0] for column in cursor.description]
        rows = cursor.fetchall()

    customers = pd.DataFrame.from_records(rows, columns=column_names)
    print(customers)


if __name__ == "__main__":
    main()
