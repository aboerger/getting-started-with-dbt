CREATE TABLE [jaffle_shop].[order_items] (

	[order_item_id] varchar(36) NULL, 
	[order_id] varchar(36) NULL, 
	[product_id] varchar(10) NULL, 
	[ordered_at] date NULL, 
	[product_name] varchar(100) NULL, 
	[product_price] numeric(16,2) NULL, 
	[is_food_item] bit NULL, 
	[is_drink_item] bit NULL, 
	[supply_cost] numeric(38,2) NULL
);