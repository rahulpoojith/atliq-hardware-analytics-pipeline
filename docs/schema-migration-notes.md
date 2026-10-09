# MySQL to SQL Server schema notes

These are proposed SQL Server type mappings for review. The source dump remains unchanged.

| MySQL source type | SQL Server candidate | Reason / validation |
| --- | --- | --- |
| `INT UNSIGNED` | `BIGINT` | Preserves the full unsigned 32-bit range. Used by customer codes and sold quantity. |
| `VARCHAR(n)` | `NVARCHAR(n)` | Preserves Unicode text, including product/customer names with non-ASCII characters. |
| `YEAR` | `SMALLINT` | Stores the source year values as a numeric year; validate allowed values and whether any nulls occur. |
| `DECIMAL(p,s) UNSIGNED` | `DECIMAL(p,s)` | SQL Server has no unsigned decimal; source values are nonnegative, so validate that before load. |
| `DATE` | `DATE` | Direct equivalent for the monthly sales date. |

## Table grains and candidate relationships

- `dim_customer`: one row per `customer_code` (candidate key; verify uniqueness before adding a constraint).
- `dim_product`: one row per `product_code` (candidate key; verify uniqueness before adding a constraint).
- `fact_sales_monthly`: likely one row per (`date`, `product_code`, `customer_code`); validate this combination for duplicates.
- `fact_gross_price`: likely one row per (`product_code`, `fiscal_year`).
- `fact_manufacturing_cost`: likely one row per (`product_code`, `cost_year`).
- `fact_pre_invoice_deductions`: likely one row per (`customer_code`, `fiscal_year`).

The dump declares no primary or foreign keys. Treat these as hypotheses until checked against loaded rows. Product names include non-ASCII text, so Unicode-capable target columns are preferred even though the source declarations use `latin1`.

## Migration sequencing

1. Define SQL Server tables using reviewed types.
2. Convert/transfer data in a repeatable way without executing the MySQL dump in SSMS.
3. Compare source and target row counts and inspect nulls, numeric ranges, duplicates, and joins.
4. Add keys only after validation.
