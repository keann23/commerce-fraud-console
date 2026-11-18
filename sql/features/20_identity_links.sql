-- Identity graph: which accounts share a device, a card, or an inbox (after normalization).
-- identity_links is a bipartite list (account -> thing it used). The Ring Explorer draws it directly.
-- identity_clusters groups accounts into connected components: if A shares a device with B and
-- B shares a card with C, then A, B and C are one cluster, even though A and C share nothing.

CREATE OR REPLACE TABLE identity_links AS
WITH device_use AS (
    SELECT user_id, signup_device_id AS device_id FROM users WHERE signup_device_id IS NOT NULL
    UNION SELECT user_id, device_id FROM logins WHERE device_id IS NOT NULL
    UNION SELECT user_id, device_id FROM transactions WHERE device_id IS NOT NULL
)
SELECT user_id, 'device' AS link_type, device_id AS link_value FROM device_use
UNION
SELECT user_id, 'card', card_fingerprint FROM payment_methods
UNION
SELECT user_id, 'email', email_normalized FROM users;

-- Values shared by more than 50 accounts (a big public terminal, a corporate card) are treated as
-- infrastructure, not identity: linking through them would merge thousands of strangers.
CREATE OR REPLACE TABLE identity_clusters AS
WITH RECURSIVE shared AS (
    SELECT link_type, link_value, min(user_id) AS anchor
    FROM identity_links
    GROUP BY ALL
    HAVING count(*) BETWEEN 2 AND 50
),
edges AS (  -- star edges to one anchor per shared value: same components, far fewer edges than all pairs
    SELECT l.user_id AS src, s.anchor AS dst
    FROM identity_links l JOIN shared s USING (link_type, link_value)
    WHERE l.user_id <> s.anchor
    UNION
    SELECT s.anchor, l.user_id
    FROM identity_links l JOIN shared s USING (link_type, link_value)
    WHERE l.user_id <> s.anchor
),
walk(user_id, root) AS (
    SELECT user_id, user_id FROM users
    UNION
    SELECT e.dst, w.root FROM walk w JOIN edges e ON e.src = w.user_id
)
SELECT user_id, 'C' || min(root) AS cluster_id
FROM walk
GROUP BY user_id;
