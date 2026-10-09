-- SQL Server schema for the source MySQL dim_customer table.
-- This creates the table only; it does not load rows or add unverified keys.

CREATE TABLE dbo.dim_customer (
    customer_code BIGINT NOT NULL,
    customer NVARCHAR(150) NOT NULL,
    platform NVARCHAR(45) NOT NULL,
    channel NVARCHAR(45) NOT NULL,
    market NVARCHAR(45) NULL,
    sub_zone NVARCHAR(45) NULL,
    region NVARCHAR(45) NULL
);
