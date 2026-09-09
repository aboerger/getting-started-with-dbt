CREATE TABLE [jaffle_shop].[supplies] (
    [supply_uuid]          VARCHAR (50)    NULL,
    [supply_id]            VARCHAR (10)    NULL,
    [product_id]           VARCHAR (10)    NULL,
    [supply_name]          VARCHAR (100)   NULL,
    [supply_cost]          NUMERIC (16, 2) NULL,
    [is_perishable_supply] BIT             NULL
);


GO

CREATE CLUSTERED COLUMNSTORE INDEX [jaffle_shop_supplies__dbt_tmp_cci]
    ON [jaffle_shop].[supplies];


GO

