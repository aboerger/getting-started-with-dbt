CREATE TABLE [jaffle_shop].[locations] (
    [location_id]   VARCHAR (36) NULL,
    [location_name] VARCHAR (50) NULL,
    [tax_rate]      FLOAT (53)   NULL,
    [opened_date]   DATE         NULL
);


GO

CREATE CLUSTERED COLUMNSTORE INDEX [jaffle_shop_locations__dbt_tmp_cci]
    ON [jaffle_shop].[locations];


GO

