CREATE TABLE [jaffle_shop].[customers] (
    [customer_id]           VARCHAR (36)    NULL,
    [customer_name]         VARCHAR (100)   NULL,
    [count_lifetime_orders] INT             NULL,
    [first_ordered_at]      DATE            NULL,
    [last_ordered_at]       DATE            NULL,
    [lifetime_spend_pretax] NUMERIC (38, 2) NULL,
    [lifetime_tax_paid]     NUMERIC (38, 2) NULL,
    [lifetime_spend]        NUMERIC (38, 2) NULL,
    [customer_type]         VARCHAR (9)     NOT NULL
);


GO

CREATE CLUSTERED COLUMNSTORE INDEX [jaffle_shop_customers__dbt_tmp_cci]
    ON [jaffle_shop].[customers];


GO

