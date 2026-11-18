-- ATO victims and friendly-fraud customers are protected or represented, never blocked.
SELECT pattern, entity_id, recommended_action
FROM {{ ref('scored_entities') }}
WHERE pattern IN ('ato', 'friendly_fraud') AND recommended_action = 'block'
