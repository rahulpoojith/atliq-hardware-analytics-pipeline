# AtliQ Hardware Analytics Pipeline

Learning project for moving the AtliQ Hardware dataset into SQL Server and building a Python analytics pipeline.

## Source data

- `atliq_hardware_db.sql` is a MySQL 8 dump. Do not run it directly in SQL Server.
- `Metadata.txt` describes the six source tables.
- `Ad-Hoc Requests.pdf` contains business analysis questions.
- `hints_for_answering_questions.docx` contains reference hints.

## Planned workflow

1. Inspect and document source schema and data characteristics.
2. Convert the MySQL dump into SQL Server-compatible tables and load data.
3. Validate table counts, types, and relationships in SQL Server.
4. Connect Python on macOS to SQL Server and extract data for analysis.
5. Answer business questions and explain the results.

The work will proceed in small, validated steps. Credentials and generated staging files should stay out of Git.
