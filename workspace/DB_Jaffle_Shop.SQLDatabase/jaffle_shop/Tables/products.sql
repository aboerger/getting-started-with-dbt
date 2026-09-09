CREATE TABLE [jaffle_shop].[products] (
    [product_id]          VARCHAR (10)    NULL,
    [product_name]        VARCHAR (100)   NULL,
    [product_type]        VARCHAR (20)    NULL,
    [product_description] VARCHAR (200)   NULL,
    [product_price]       NUMERIC (16, 2) NULL,
    [is_food_item]        BIT             NULL,
    [is_drink_item]       BIT             NULL
);


GO

CREATE CLUSTERED COLUMNSTORE INDEX [jaffle_shop_products__dbt_tmp_cci]
    ON [jaffle_shop].[products];


GO

