# Diferencias entre entregas

- **A (anterior):** `data/raw_backup`
- **B (actual):** `data/raw`

## customers

| | A | B |
|---|---|---|
| filas | 150,000 | 150,000 |
| IDs distintos | 150,000 | 150,000 |

- Columnas solo en A: —
- Columnas solo en B: —
- IDs solo en A: 145,975 · IDs solo en B: 145,975 · IDs comunes con contenido distinto: 1,786

| columna que cambia | filas |
|---|---|
| credit_score | 1,525 |
| first_name | 1,252 |
| email | 1,236 |
| last_name | 1,203 |
| city | 1,128 |
| state | 1,128 |
| address | 1,107 |
| date_of_birth | 1,089 |
| postal_code | 1,065 |
| document_number | 1,052 |
| estimated_monthly_income | 929 |
| gender | 850 |

## products

| | A | B |
|---|---|---|
| filas | 400,000 | 400,000 |
| IDs distintos | 400,000 | 400,000 |

- Columnas solo en A: —
- Columnas solo en B: —
- IDs solo en A: 271,401 · IDs solo en B: 271,401 · IDs comunes con contenido distinto: 128,599

| columna que cambia | filas |
|---|---|
| customer_id | 128,599 |
| opening_branch_id | 76,143 |
| current_balance | 70,841 |
| currency | 67,168 |
| credit_limit | 22,771 |
| product_number | 7,151 |
| interest_rate | 6,666 |
| last_transaction_date | 6,496 |
| last_updated | 6,462 |
| opening_date | 6,458 |
| opening_channel | 5,991 |
| product_type | 5,448 |

## transactions

| | A | B |
|---|---|---|
| filas | 1,839,229 | 4,425,008 |
| IDs distintos | 1,839,229 | 4,425,008 |
| particiones | 2023-07-01 → 2024-09-25 (453 archivos) | 2023-06-17 → 2026-06-17 (1097 archivos) |

- Columnas solo en A: —
- Columnas solo en B: —
- IDs solo en A: 1,777,868 · IDs solo en B: 4,363,647 · IDs comunes con contenido distinto: 61,361

| columna que cambia | filas |
|---|---|
| product_id | 61,361 |
| customer_id | 61,361 |
| transaction_date | 60,566 |
| process_date | 60,076 |
| transaction_city | 50,403 |
| amount | 49,622 |
| transaction_country | 37,971 |
| currency | 35,964 |
| amount_usd | 34,948 |
| transaction_type | 27,755 |
| branch_id | 21,128 |
| channel | 18,877 |

## complaints

| | A | B |
|---|---|---|
| filas | 67,095 | 67,095 |
| IDs distintos | 67,095 | 67,095 |
| particiones | 2023-06-17 → 2026-06-17 (1097 archivos) | 2023-06-17 → 2026-06-17 (1097 archivos) |

- Columnas solo en A: —
- Columnas solo en B: —
- IDs solo en A: 0 · IDs solo en B: 0 · IDs comunes con contenido distinto: 67,095

| columna que cambia | filas |
|---|---|
| customer_id | 67,095 |
| affected_product_id | 44,551 |
| assigned_agent_id | 22,071 |

