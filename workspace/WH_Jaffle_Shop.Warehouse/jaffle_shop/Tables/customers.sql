CREATE TABLE [jaffle_shop].[customers] (

	[customer_id] varchar(36) NULL, 
	[customer_name] varchar(100) NULL, 
	[count_lifetime_orders] int NULL, 
	[first_ordered_at] date NULL, 
	[last_ordered_at] date NULL, 
	[lifetime_spend_pretax] numeric(38,2) NULL, 
	[lifetime_tax_paid] numeric(38,2) NULL, 
	[lifetime_spend] numeric(38,2) NULL, 
	[customer_type] varchar(9) NOT NULL
);