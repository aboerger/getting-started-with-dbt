CREATE TABLE [raw].[raw_orders] (

	[id] varchar(36) NULL, 
	[customer] varchar(36) NULL, 
	[ordered_at] datetime2(6) NULL, 
	[store_id] varchar(36) NULL, 
	[subtotal] int NULL, 
	[tax_paid] int NULL, 
	[order_total] int NULL
);