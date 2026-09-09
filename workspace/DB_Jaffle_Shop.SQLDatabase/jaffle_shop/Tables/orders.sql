CREATE TABLE [jaffle_shop].[orders] (
    [order_id]              VARCHAR (36)    NULL,
    [location_id]           VARCHAR (36)    NULL,
    [customer_id]           VARCHAR (36)    NULL,
    [subtotal_cents]        INT             NULL,
    [tax_paid_cents]        INT             NULL,
    [order_total_cents]     INT             NULL,
    [subtotal]              NUMERIC (16, 2) NULL,
    [tax_paid]              NUMERIC (16, 2) NULL,
    [order_total]           NUMERIC (16, 2) NULL,
    [ordered_at]            DATE            NULL,
    [order_cost]            NUMERIC (38, 2) NULL,
    [order_items_subtotal]  NUMERIC (38, 2) NULL,
    [count_food_items]      INT             NULL,
    [count_drink_items]     INT             NULL,
    [count_order_items]     INT             NULL,
    [is_food_order]         BIT             NULL,
    [is_drink_order]        BIT             NULL,
    [customer_order_number] BIGINT          NULL
);


GO

CREATE CLUSTERED COLUMNSTORE INDEX [jaffle_shop_orders__dbt_tmp_cci]
    ON [jaffle_shop].[orders];


GO

