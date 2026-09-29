import duckdb, pandas as pd
pd.set_option("display.width", 250, "display.max_colwidth", 90)
con = duckdb.connect("data/bank.duckdb", read_only=True)
def q(t, s): print(f"\n### {t}\n", con.execute(s).df().to_string(index=False))
q("Texto cliente vs categoría (top textos)", """
SELECT left(t.customer_text,70) txt, i.reason_category, count(*) n FROM raw_call_transcripts t JOIN raw_call_center_interactions i USING(interaction_id)
GROUP BY txt, i.reason_category QUALIFY row_number() OVER (PARTITION BY txt ORDER BY n DESC) <= 6 ORDER BY txt, n DESC LIMIT 36""")
q("Moneda por país de transacción", "SELECT transaction_country, currency, count(*) n FROM raw_transactions GROUP BY ALL ORDER BY 1, n DESC")
q("Moneda productos por país cliente", "SELECT c.country, p.currency, count(*) n FROM raw_products p JOIN raw_customers c USING(customer_id) GROUP BY ALL ORDER BY 1, n DESC")
q("Fraude por canal", "SELECT channel, count(*) n, round(100*avg((lower(is_fraud)='true')::INT),3) fraud_pct FROM raw_transactions GROUP BY ALL ORDER BY fraud_pct DESC")
q("Fraude por país trx != país cliente", """SELECT t.transaction_country <> c.country foreign_trx, count(*) n, round(100*avg((lower(is_fraud)='true')::INT),3) fraud_pct
FROM raw_transactions t JOIN raw_customers c USING(customer_id) GROUP BY ALL""")
q("Fraude por decil de monto", """SELECT d, round(min(a)) lo, round(max(a)) hi, count(*) n, round(100*avg(f),3) fraud_pct FROM
(SELECT try_cast(amount AS DOUBLE) a, (lower(is_fraud)='true')::INT f, ntile(10) OVER (ORDER BY try_cast(amount AS DOUBLE)) d FROM raw_transactions) GROUP BY d ORDER BY d""")
q("Fraude por hora", """SELECT hour(try_cast(transaction_date AS TIMESTAMP)) h, round(100*avg((lower(is_fraud)='true')::INT),3) fraud_pct FROM raw_transactions GROUP BY ALL ORDER BY fraud_pct DESC LIMIT 6""")
q("AUC aprox de fraud_score (ranking)", """WITH s AS (SELECT try_cast(fraud_score AS DOUBLE) sc, (lower(is_fraud)='true')::INT y FROM raw_transactions WHERE fraud_score IS NOT NULL),
r AS (SELECT y, rank() OVER (ORDER BY sc) rk FROM s)
SELECT (sum(rk) FILTER (WHERE y=1) - count(*) FILTER (WHERE y=1)*(count(*) FILTER (WHERE y=1)+1)/2.0) / (count(*) FILTER (WHERE y=1)*count(*) FILTER (WHERE y=0)) auc,
 count(*) FILTER (WHERE y=1) pos FROM r""")
q("Casi-duplicados trx (mismo cliente, monto, timestamp)", """SELECT count(*) - count(DISTINCT (customer_id, amount, transaction_date)) near_dups, count(*) n FROM raw_transactions""")
q("Casi-duplicados interacciones", """SELECT count(*) - count(DISTINCT (customer_id, interaction_date, reason_category)) near_dups, count(*) n FROM raw_call_center_interactions""")
q("Formatos de booleanos/fechas raros", """SELECT was_resolved, count(*) n FROM raw_call_center_interactions GROUP BY ALL""")
q("Estado de clientes / productos", "SELECT customer_status, count(*) n FROM raw_customers GROUP BY ALL")
q("Tipos de producto", "SELECT product_type, product_status, count(*) n FROM raw_products GROUP BY ALL ORDER BY n DESC LIMIT 25")
