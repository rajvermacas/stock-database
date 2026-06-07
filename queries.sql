SELECT *
FROM read_parquet('market-data/prices')
LIMIT 100;