CREATE TABLE [jaffle_shop].[products] (

	[product_id] varchar(10) NULL, 
	[product_name] varchar(100) NULL, 
	[product_type] varchar(20) NULL, 
	[product_description] varchar(200) NULL, 
	[product_price] numeric(16,2) NULL, 
	[is_food_item] bit NULL, 
	[is_drink_item] bit NULL
);