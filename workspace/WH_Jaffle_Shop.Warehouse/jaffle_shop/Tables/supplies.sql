CREATE TABLE [jaffle_shop].[supplies] (

	[supply_uuid] varchar(400) NULL, 
	[supply_id] varchar(10) NULL, 
	[product_id] varchar(10) NULL, 
	[supply_name] varchar(100) NULL, 
	[supply_cost] numeric(16,2) NULL, 
	[is_perishable_supply] bit NULL
);