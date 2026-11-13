# Daily Gmail pull (~06:30 America/El_Salvador)
Runs as a scheduled assistant routine (outside Databricks), read-only Gmail (jg0592@gmail.com).

Query:
`from:(soluciones@promericaotp.com.sv OR alertas_tarjeta@credicomer.com.sv OR notificaciones_clientes@credicomer.com.sv OR noreply@bi.com.sv OR notificaciones@bancocuscatlan.com OR info@baccredomatic.com) newer_than:2d`

Body fetched for BI, BAC, Pago de Colector, Pago de tarjeta propio, Credicomer card alerts; snippet otherwise.
Saved as `{id, thread_id, from, subject, date, snippet, body}` list, then:
`python3 scripts/daily_gmail_ingest.py <messages.json>`
