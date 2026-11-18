-- Fails if a detection scores the same entity twice.
SELECT pattern, entity_type, entity_id, count(*) AS n
FROM {{ ref('scored_entities') }}
GROUP BY ALL
HAVING count(*) > 1
