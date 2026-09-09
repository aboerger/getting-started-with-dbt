CREATE TABLE [raw].[raw_orders] (
    [id]          VARCHAR (36)  NULL,
    [customer]    VARCHAR (36)  NULL,
    [ordered_at]  DATETIME2 (6) NULL,
    [store_id]    VARCHAR (36)  NULL,
    [subtotal]    INT           NULL,
    [tax_paid]    INT           NULL,
    [order_total] INT           NULL
);


GO

