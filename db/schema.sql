-- HM Land Registry Price Paid Data transactions (England & Wales)
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT,
    price BIGINT,
    date_of_transfer TIMESTAMP,
    postcode TEXT,
    postcode_area TEXT,
    property_type CHAR(1),
    property_type_label TEXT,
    new_build CHAR(1),
    duration CHAR(1),
    paon TEXT,
    saon TEXT,
    street TEXT,
    locality TEXT,
    town TEXT,
    district TEXT,
    county TEXT,
    ppd_category CHAR(1),
    record_status CHAR(1)
);

CREATE INDEX IF NOT EXISTS idx_transactions_property_type ON transactions (property_type);
CREATE INDEX IF NOT EXISTS idx_transactions_district ON transactions (district);
CREATE INDEX IF NOT EXISTS idx_transactions_county ON transactions (county);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions (date_of_transfer);
CREATE INDEX IF NOT EXISTS idx_transactions_postcode_area ON transactions (postcode_area);
