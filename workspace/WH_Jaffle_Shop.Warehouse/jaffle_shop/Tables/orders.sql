CREATE TABLE [jaffle_shop].[orders] (

	[order_id] varchar(36) NULL, 
	[location_id] varchar(36) NULL, 
	[customer_id] varchar(36) NULL, 
	[subtotal_cents] int NULL, 
	[tax_paid_cents] int NULL, 
	[order_total_cents] int NULL, 
	[subtotal] numeric(16,2) NULL, 
	[tax_paid] numeric(16,2) NULL, 
	[order_total] numeric(16,2) NULL, 
	[ordered_at] date NULL, 
	[order_cost] numeric(38,2) NULL, 
	[order_items_subtotal] numeric(38,2) NULL, 
	[count_food_items] int NULL, 
	[count_drink_items] int NULL, 
	[count_order_items] int NULL, 
	[is_food_order] bit NULL, 
	[is_drink_order] bit NULL, 
	[customer_order_number] bigint NULL
);