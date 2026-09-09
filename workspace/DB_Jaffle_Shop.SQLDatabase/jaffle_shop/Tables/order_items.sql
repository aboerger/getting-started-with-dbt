CREATE TABLE [jaffle_shop].[order_items] (
    [order_item_id] VARCHAR (36)    NULL,
    [order_id]      VARCHAR (36)    NULL,
    [product_id]    VARCHAR (10)    NULL,
    [ordered_at]    DATE            NULL,
    [product_name]  VARCHAR (100)   NULL,
    [product_price] NUMERIC (16, 2) NULL,
    [is_food_item]  BIT             NULL,
    [is_drink_item] BIT             NULL,
    [supply_cost]   NUMERIC (38, 2) NULL
);


GO

CREATE CLUSTERED COLUMNSTORE INDEX [jaffle_shop_order_items__dbt_tmp_cci]
    ON [jaffle_shop].[order_items];


GO

