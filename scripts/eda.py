"""EDA orientado a elegir el flujo de atención. Lee data/bank.duckdb (tablas raw_*) y escribe reports/eda_output.txt."""
import duckdb, os, sys
import pandas as pd

pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_colwidth", 80, "display.max_rows", 200)
con = duckdb.connect("data/bank.duckdb", read_only=True)
os.makedirs("reports", exist_ok=True)
out = open("reports/eda_output.txt", "w", encoding="utf-8")

def q(title, sql):
    df = con.execute(sql).df()
    txt = f"\n### {title}\n{df.to_string(index=False)}\n"
    print(txt); out.write(txt); out.flush()
    return df

tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'raw_%' ORDER BY 1").fetchall()]
PK = {"raw_customers": "customer_id", "raw_products": "product_id", "raw_branches": "branch_id",
      "raw_service_agents": "agent_id", "raw_marketing_campaigns": "campaign_id", "raw_transactions": "transaction_id",
      "raw_call_center_interactions": "interaction_id", "raw_call_transcripts": "transcript_id",
      "raw_satisfaction_surveys": "survey_id", "raw_complaints": "complaint_id", "raw_campaign_sends": "send_id",
      "raw_digital_events": "event_id"}

# ---------- 1. Calidad de datos ----------
rows = []
for t in tables:
    cols = [c[0] for c in con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{t}'").fetchall()]
    n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    pk = PK.get(t)
    dup_pk = con.execute(f"SELECT count(*) - count(DISTINCT {pk}) FROM {t}").fetchone()[0] if pk in cols else None
    body = [c for c in cols if c not in ("filename","year","month","day")]
    dup_full = n - con.execute(f"SELECT count(*) FROM (SELECT DISTINCT {', '.join(body)} FROM {t})").fetchone()[0]
    rows.append(dict(table=t, rows=n, cols=len(body), dup_pk=dup_pk, dup_full_row=dup_full,
                     pct_dup_pk=round(100 * (dup_pk or 0) / n, 2)))
df = pd.DataFrame(rows); txt = f"\n### Filas y duplicados\n{df.to_string(index=False)}\n"; print(txt); out.write(txt)

# columnas fuera del diccionario (evolución de esquema) y % nulos por columna en tablas clave
for t in ["raw_call_center_interactions", "raw_call_transcripts", "raw_complaints", "raw_transactions", "raw_customers", "raw_products", "raw_satisfaction_surveys"]:
    cols = [c[0] for c in con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{t}'").fetchall() if c[0] not in ("filename","year","month","day")]
    exprs = ", ".join(f"round(100.0*count(*) FILTER (WHERE \"{c}\" IS NULL OR trim(CAST(\"{c}\" AS VARCHAR))='')/count(*),1) AS \"{c}\"" for c in cols)
    d = con.execute(f"SELECT {exprs} FROM {t}").df().T.reset_index(); d.columns = ["column", "pct_null"]
    txt = f"\n### % nulos {t}\n{d.to_string(index=False)}\n"; print(txt); out.write(txt)

# ---------- 2. Integridad referencial ----------
q("Huérfanos FK", """
SELECT 'interactions.customer_id' fk, count(*) FILTER (WHERE c.customer_id IS NULL) orphans, count(*) n FROM raw_call_center_interactions i LEFT JOIN (SELECT DISTINCT customer_id FROM raw_customers) c USING(customer_id)
UNION ALL SELECT 'transactions.customer_id', count(*) FILTER (WHERE c.customer_id IS NULL), count(*) FROM raw_transactions t LEFT JOIN (SELECT DISTINCT customer_id FROM raw_customers) c USING(customer_id)
UNION ALL SELECT 'transactions.product_id', count(*) FILTER (WHERE p.product_id IS NULL), count(*) FROM raw_transactions t LEFT JOIN (SELECT DISTINCT product_id FROM raw_products) p USING(product_id)
UNION ALL SELECT 'transcripts.interaction_id', count(*) FILTER (WHERE i.interaction_id IS NULL), count(*) FROM raw_call_transcripts t LEFT JOIN (SELECT DISTINCT interaction_id FROM raw_call_center_interactions) i USING(interaction_id)
UNION ALL SELECT 'complaints.affected_product_id', count(*) FILTER (WHERE a.affected_product_id IS NOT NULL AND p.product_id IS NULL), count(*) FILTER (WHERE a.affected_product_id IS NOT NULL) FROM raw_complaints a LEFT JOIN (SELECT DISTINCT product_id FROM raw_products) p ON a.affected_product_id=p.product_id
UNION ALL SELECT 'complaints.origin_interaction_id', count(*) FILTER (WHERE a.origin_interaction_id IS NOT NULL AND i.interaction_id IS NULL), count(*) FILTER (WHERE a.origin_interaction_id IS NOT NULL) FROM raw_complaints a LEFT JOIN (SELECT DISTINCT interaction_id FROM raw_call_center_interactions) i ON a.origin_interaction_id=i.interaction_id
UNION ALL SELECT 'products.customer_id', count(*) FILTER (WHERE c.customer_id IS NULL), count(*) FROM raw_products p LEFT JOIN (SELECT DISTINCT customer_id FROM raw_customers) c USING(customer_id)
""")

# ---------- 3. Llegadas tardías ----------
q("Llegadas tardías (process_date - fecha evento, días)", """
SELECT 'interactions' t, date_diff('day', try_cast(interaction_date AS TIMESTAMP)::DATE, try_cast(process_date AS DATE)) lag_days, count(*) n FROM raw_call_center_interactions GROUP BY ALL
UNION ALL SELECT 'transactions', date_diff('day', try_cast(transaction_date AS TIMESTAMP)::DATE, try_cast(process_date AS DATE)), count(*) FROM raw_transactions GROUP BY ALL
UNION ALL SELECT 'complaints', date_diff('day', try_cast(creation_date AS TIMESTAMP)::DATE, try_cast(process_date AS DATE)), count(*) FROM raw_complaints GROUP BY ALL
ORDER BY 1, 2""")

# ---------- 4. Motivos de contacto ----------
q("Valores de reason_category / contact_reason", """
SELECT reason_category, contact_reason, count(*) n FROM raw_call_center_interactions GROUP BY ALL ORDER BY n DESC LIMIT 60""")
q("KPIs por categoría de motivo", """
SELECT reason_category, count(*) n, round(100.0*n/sum(n) OVER (),1) pct,
  round(100*avg(CASE WHEN lower(was_resolved)='true' THEN 1 WHEN lower(was_resolved)='false' THEN 0 END),1) fcr_pct,
  round(100*avg(CASE WHEN lower(was_escalated)='true' THEN 1.0 ELSE 0 END),1) escal_pct,
  round(100*avg(CASE WHEN lower(requires_followup)='true' THEN 1.0 ELSE 0 END),1) followup_pct,
  round(median(try_cast(duration_seconds AS DOUBLE))) med_dur_s, round(median(try_cast(wait_time_seconds AS DOUBLE))) med_wait_s,
  round(avg(try_cast(sentiment_score AS DOUBLE)),2) avg_sent
FROM raw_call_center_interactions GROUP BY ALL ORDER BY n DESC""")
q("Canal y tipo de interacción", """
SELECT channel, interaction_type, count(*) n FROM raw_call_center_interactions GROUP BY ALL ORDER BY n DESC LIMIT 30""")
q("Volumen mensual por categoría", """
SELECT strftime(try_cast(interaction_date AS TIMESTAMP), '%Y-%m') ym, reason_category, count(*) n
FROM raw_call_center_interactions GROUP BY ALL ORDER BY ym, reason_category LIMIT 400""")
q("Hora del día", """
SELECT hour(try_cast(interaction_date AS TIMESTAMP)) h, count(*) n FROM raw_call_center_interactions GROUP BY ALL ORDER BY h""")

# ---------- 5. Transcripciones ----------
q("Intenciones detectadas (top)", """
SELECT trim(x) intent, count(*) n FROM (SELECT unnest(string_split(detected_intents, ',')) x FROM raw_call_transcripts) GROUP BY ALL ORDER BY n DESC LIMIT 40""")
q("Temas principales (top)", """
SELECT trim(x) topic, count(*) n FROM (SELECT unnest(string_split(main_topics, ',')) x FROM raw_call_transcripts) GROUP BY ALL ORDER BY n DESC LIMIT 40""")
q("Idioma / acento / calidad", """
SELECT detected_language, detected_accent, audio_quality, count(*) n FROM raw_call_transcripts GROUP BY ALL ORDER BY n DESC LIMIT 30""")
q("Intención vs categoría de la interacción", """
SELECT i.reason_category, trim(x) intent, count(*) n FROM
 (SELECT interaction_id, unnest(string_split(detected_intents, ',')) x FROM raw_call_transcripts) t
 JOIN raw_call_center_interactions i USING(interaction_id) GROUP BY ALL ORDER BY n DESC LIMIT 40""")
q("Diversidad de textos (¿plantillas?)", """
SELECT count(*) n, count(DISTINCT full_text) distinct_full, count(DISTINCT customer_text) distinct_cust,
  round(avg(length(full_text))) avg_len FROM raw_call_transcripts""")
q("Muestras de transcripciones", """
SELECT detected_intents, left(customer_text, 300) customer_text FROM raw_call_transcripts USING SAMPLE 8 ROWS (reservoir, 42)""")

# ---------- 6. Quejas (PQR) ----------
q("Quejas por tipo/categoría", """
SELECT case_type, category, count(*) n, round(100*avg(CASE WHEN lower(sla_breached)='true' THEN 1.0 ELSE 0 END),1) sla_breach_pct,
  round(median(try_cast(resolution_days AS DOUBLE)),1) med_res_days, round(100*avg(CASE WHEN status IN ('Escalated','Escalado') THEN 1.0 ELSE 0 END),1) escal_pct
FROM raw_complaints GROUP BY ALL ORDER BY n DESC LIMIT 40""")
q("Subcategorías (top)", """
SELECT category, subcategory, count(*) n FROM raw_complaints GROUP BY ALL ORDER BY n DESC LIMIT 40""")
q("Estado, prioridad, canal", """
SELECT status, priority, count(*) n FROM raw_complaints GROUP BY ALL ORDER BY n DESC LIMIT 30""")
q("Muestras de descripción de queja", """
SELECT category, subcategory, claimed_amount, currency, left(description, 250) description FROM raw_complaints USING SAMPLE 8 ROWS (reservoir, 7)""")

# ---------- 7. Transacciones ----------
q("Transacciones: tipo/estado/fraude", """
SELECT transaction_type, transaction_status, count(*) n, round(100*avg(CASE WHEN lower(is_fraud)='true' THEN 1.0 ELSE 0 END),3) fraud_pct,
  round(avg(try_cast(fraud_score AS DOUBLE)),1) avg_score FROM raw_transactions GROUP BY ALL ORDER BY n DESC LIMIT 40""")
q("Fraud score vs is_fraud", """
SELECT is_fraud, count(*) n, round(avg(try_cast(fraud_score AS DOUBLE)),1) avg_score, round(quantile_cont(try_cast(fraud_score AS DOUBLE),0.9),1) p90
FROM raw_transactions GROUP BY ALL""")
q("Monedas/canal", """
SELECT currency, channel, count(*) n FROM raw_transactions GROUP BY ALL ORDER BY n DESC LIMIT 25""")

# ---------- 8. Acento: match vs satisfacción/FCR ----------
q("Match de acento vs FCR / sentimiento", """
SELECT customer_detected_accent = agent_used_accent accent_match, count(*) n,
  round(100*avg(CASE WHEN lower(was_resolved)='true' THEN 1 WHEN lower(was_resolved)='false' THEN 0 END),2) fcr_pct,
  round(100*avg(CASE WHEN lower(was_escalated)='true' THEN 1.0 ELSE 0 END),2) escal_pct,
  round(avg(try_cast(sentiment_score AS DOUBLE)),3) avg_sent
FROM raw_call_center_interactions WHERE customer_detected_accent IS NOT NULL AND agent_used_accent IS NOT NULL GROUP BY ALL""")
q("Match de acento vs CSAT", """
SELECT i.customer_detected_accent = i.agent_used_accent accent_match, s.survey_type, count(*) n,
  round(avg(try_cast(s.main_score AS DOUBLE)),3) avg_score
FROM raw_satisfaction_surveys s JOIN raw_call_center_interactions i USING(interaction_id)
WHERE i.customer_detected_accent IS NOT NULL AND i.agent_used_accent IS NOT NULL GROUP BY ALL ORDER BY 2,1""")
q("Acento cliente x acento agente", """
SELECT customer_detected_accent, agent_used_accent, count(*) n,
  round(100*avg(CASE WHEN lower(was_resolved)='true' THEN 1 WHEN lower(was_resolved)='false' THEN 0 END),2) fcr_pct
FROM raw_call_center_interactions GROUP BY ALL ORDER BY 1, 2""")

# ---------- 9. Segmento / país ----------
q("KPIs por país y segmento", """
SELECT c.country, c.segment, count(*) n,
  round(100*avg(CASE WHEN lower(i.was_resolved)='true' THEN 1 WHEN lower(i.was_resolved)='false' THEN 0 END),2) fcr_pct,
  round(100*avg(CASE WHEN lower(i.was_escalated)='true' THEN 1.0 ELSE 0 END),2) escal_pct
FROM raw_call_center_interactions i JOIN (SELECT DISTINCT customer_id, country, segment FROM raw_customers) c USING(customer_id)
GROUP BY ALL ORDER BY 1, 2""")
q("Valores de país (limpieza)", """SELECT country, count(*) n FROM raw_customers GROUP BY ALL ORDER BY n DESC""")
out.close()
