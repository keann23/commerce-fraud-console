-- Fails (returns rows) if any detection emits a score outside 0..100.
SELECT pattern, entity_type, entity_id, risk_score
FROM {{ ref('scored_entities') }}
WHERE risk_score NOT BETWEEN 0 AND 100
