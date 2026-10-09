"""Convert the AtliQ MySQL dump to a SQL Server T-SQL script.

The source dump is read only. The generated script creates missing tables and
inserts rows in batches of at most 1,000 (SQL Server's VALUES row limit).
"""

import argparse
import os
import re
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT_ROOT / "atliq_hardware_db.sql"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "atliq_hardware_mssql.sql"


# Column names, SQL Server types, and nullability are explicit and trusted.
# The dump declares no keys; candidate keys are intentionally deferred until
# the imported data has been checked for duplicates and orphan rows.
TABLES = {
    "dim_customer": [
        ("customer_code", "BIGINT", False),
        ("customer", "NVARCHAR(150)", False),
        ("platform", "NVARCHAR(45)", False),
        ("channel", "NVARCHAR(45)", False),
        ("market", "NVARCHAR(45)", True),
        ("sub_zone", "NVARCHAR(45)", True),
        ("region", "NVARCHAR(45)", True),
    ],
    "dim_product": [
        ("product_code", "NVARCHAR(45)", False),
        ("division", "NVARCHAR(45)", False),
        ("segment", "NVARCHAR(45)", False),
        ("category", "NVARCHAR(45)", False),
        ("product", "NVARCHAR(200)", False),
        ("variant", "NVARCHAR(45)", True),
    ],
    "fact_gross_price": [
        ("product_code", "NVARCHAR(45)", False),
        ("fiscal_year", "SMALLINT", False),
        ("gross_price", "DECIMAL(15,4)", False),
    ],
    "fact_manufacturing_cost": [
        ("product_code", "NVARCHAR(45)", False),
        ("cost_year", "SMALLINT", False),
        ("manufacturing_cost", "DECIMAL(15,4)", False),
    ],
    "fact_pre_invoice_deductions": [
        ("customer_code", "BIGINT", False),
        ("fiscal_year", "SMALLINT", False),
        ("pre_invoice_discount_pct", "DECIMAL(5,4)", False),
    ],
    "fact_sales_monthly": [
        ("date", "DATE", False),
        ("product_code", "NVARCHAR(45)", False),
        ("customer_code", "BIGINT", False),
        ("sold_quantity", "BIGINT", False),
        ("fiscal_year", "SMALLINT", True),
    ],
}

INSERT_PREFIX = re.compile(
    r"^\s*INSERT\s+INTO\s+`(?P<table>[A-Za-z0-9_]+)`\s+VALUES\s*",
    re.IGNORECASE,
)
INTEGER_LITERAL = re.compile(r"^[+-]?\d+$")

MYSQL_ESCAPES = {
    "0": "\0",
    "b": "\b",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "Z": "\x1a",
    "\\": "\\",
    "'": "'",
    '"': '"',
}


class DumpFormatError(ValueError):
    """Raised when an INSERT statement isn't in the expected dump format."""


def parse_literal(text):
    """Convert one unquoted MySQL SQL literal to a Python value."""
    value = text.strip()
    if value.upper() == "NULL":
        return None
    if INTEGER_LITERAL.match(value):
        return int(value)
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise DumpFormatError("unsupported unquoted SQL literal: " + value) from exc


def iter_insert_rows(values_text, expected_columns):
    """Yield tuples from a MySQL VALUES list, respecting quoted delimiters."""
    index = 0
    length = len(values_text)

    def skip_space(position):
        while position < length and values_text[position].isspace():
            position += 1
        return position

    while True:
        index = skip_space(index)
        if index >= length or values_text[index] == ";":
            return
        if values_text[index] != "(":
            raise DumpFormatError("expected '(' before row values")
        index += 1
        row = []

        while True:
            index = skip_space(index)
            if index >= length:
                raise DumpFormatError("unexpected end of INSERT row")

            if values_text[index] == "'":
                index += 1
                chars = []
                while index < length:
                    char = values_text[index]
                    if char == "\\":
                        index += 1
                        if index >= length:
                            raise DumpFormatError("unfinished backslash escape")
                        escaped = values_text[index]
                        chars.append(MYSQL_ESCAPES.get(escaped, "\\" + escaped))
                        index += 1
                    elif char == "'":
                        if index + 1 < length and values_text[index + 1] == "'":
                            chars.append("'")
                            index += 2
                        else:
                            index += 1
                            break
                    else:
                        chars.append(char)
                        index += 1
                else:
                    raise DumpFormatError("unterminated quoted string")
                row.append("".join(chars))
                index = skip_space(index)
            else:
                start = index
                while index < length and values_text[index] not in ",);":
                    index += 1
                row.append(parse_literal(values_text[start:index]))

            if len(row) > expected_columns:
                raise DumpFormatError("row has more values than the table has columns")
            if index >= length:
                raise DumpFormatError("unexpected end after a value")
            delimiter = values_text[index]
            if delimiter == ",":
                index += 1
                continue
            if delimiter == ")":
                index += 1
                break
            raise DumpFormatError("expected ',' or ')' after a value")

        if len(row) != expected_columns:
            raise DumpFormatError(
                "row has {} values; expected {}".format(len(row), expected_columns)
            )
        yield tuple(row)

        index = skip_space(index)
        if index < length and values_text[index] == ",":
            index += 1
        elif index < length and values_text[index] == ";":
            return
        elif index >= length:
            return
        else:
            raise DumpFormatError("expected ',' or ';' between rows")


def sql_literal(value):
    """Render a parsed value as a safe T-SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "N'{}'".format(value.replace("'", "''"))
    if isinstance(value, (int, Decimal)):
        return str(value)
    raise DumpFormatError("unsupported parsed value type: " + type(value).__name__)


def write_schema(output):
    output.write("USE [AtliqHardware];\nGO\n\n")
    output.write("SET XACT_ABORT ON;\nBEGIN TRANSACTION;\nGO\n\n")
    for table_name, columns in TABLES.items():
        output.write(
            "IF OBJECT_ID(N'dbo.{0}', N'U') IS NULL\nBEGIN\n".format(table_name)
        )
        output.write("    CREATE TABLE dbo.[{0}] (\n".format(table_name))
        definitions = []
        for column_name, sql_type, nullable in columns:
            nullability = "NULL" if nullable else "NOT NULL"
            definitions.append(
                "        [{0}] {1} {2}".format(column_name, sql_type, nullability)
            )
        output.write(",\n".join(definitions))
        output.write("\n    );\nEND;\nGO\n\n")

    empty_checks = [
        "EXISTS (SELECT 1 FROM dbo.[{0}])".format(table_name)
        for table_name in TABLES
    ]
    output.write("IF " + " OR ".join(empty_checks) + "\n")
    output.write(
        "    THROW 51000, N'Target tables must be empty before this load; "
        "no rows were added.', 1;\nGO\n\n"
    )


def write_table_insert(output, table_name, rows, batch_size):
    columns = TABLES[table_name]
    names = ", ".join("[{}]".format(column[0]) for column in columns)
    output.write(
        "-- Data for dbo.{0}\nINSERT INTO dbo.[{0}] ({1})\nVALUES\n".format(
            table_name, names
        )
    )
    for row_number, row in enumerate(rows):
        suffix = ";\n" if row_number == len(rows) - 1 else ",\n"
        output.write("    ({}){}".format(", ".join(map(sql_literal, row)), suffix))
    output.write("GO\n\n")


def convert(source_path, output_path, batch_size):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {table_name: 0 for table_name in TABLES}
    found_inserts = set()
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=str(output_path.parent),
            prefix=output_path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            write_schema(output)

            with source_path.open("r", encoding="utf-8-sig", newline="") as source:
                for line_number, line in enumerate(source, start=1):
                    if not line.lstrip().upper().startswith("INSERT INTO"):
                        continue
                    match = INSERT_PREFIX.match(line)
                    if not match:
                        raise DumpFormatError(
                            "line {}: INSERT statement format wasn't recognized".format(
                                line_number
                            )
                        )
                    table_name = match.group("table")
                    if table_name not in TABLES:
                        raise DumpFormatError(
                            "line {}: unexpected table {}".format(line_number, table_name)
                        )
                    if not line.rstrip().endswith(";"):
                        raise DumpFormatError(
                            "line {}: expected the complete INSERT on one line".format(
                                line_number
                            )
                        )

                    found_inserts.add(table_name)
                    values_text = line[match.end() :]
                    batch = []
                    for row in iter_insert_rows(values_text, len(TABLES[table_name])):
                        batch.append(row)
                        counts[table_name] += 1
                        if len(batch) == batch_size:
                            write_table_insert(output, table_name, batch, batch_size)
                            batch = []
                    if batch:
                        write_table_insert(output, table_name, batch, batch_size)

            missing = set(TABLES) - found_inserts
            if missing:
                raise DumpFormatError(
                    "no INSERT statements found for: " + ", ".join(sorted(missing))
                )
            if any(count == 0 for count in counts.values()):
                raise DumpFormatError("one or more tables had no data rows")

            output.write("COMMIT TRANSACTION;\nGO\n")

        os.replace(str(temporary_path), str(output_path))
        temporary_path = None
        return counts
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="Convert the AtliQ MySQL dump into SQL Server T-SQL."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="rows per INSERT statement (maximum 1000; default 500)",
    )
    args = parser.parse_args()

    if not 1 <= args.batch_size <= 1000:
        parser.error("--batch-size must be between 1 and 1000")
    if not args.source.is_file():
        parser.error("source dump not found: {}".format(args.source))
    if args.source.resolve() == args.output.resolve():
        parser.error("output path must differ from the source dump")

    try:
        counts = convert(args.source, args.output, args.batch_size)
    except (OSError, UnicodeError, DumpFormatError) as exc:
        print("Conversion stopped safely: {}".format(exc), file=sys.stderr)
        return 1

    print("Generated: {}".format(args.output))
    for table_name, count in counts.items():
        print("  {}: {:,} rows".format(table_name, count))
    print("The MySQL source was not modified and the T-SQL script was not executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
