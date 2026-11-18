-- Reusable SQL building blocks shared by feature views and detections.
-- Kept in SQL (not Python) so every detection rule is fully expressed in the warehouse.

-- Email normalization ------------------------------------------------------
-- Fraudsters mint "new" identities from one inbox:
--   Gmail ignores dots in the local part (k.e.an@gmail.com == kean@gmail.com)
--   Most providers ignore everything after '+' (kean+7@gmail.com == kean@gmail.com)
--   Addresses are case-insensitive in practice.
-- Normalizing collapses those back to one inbox so we can count identities, not strings.
CREATE OR REPLACE MACRO email_local(e)  AS split_part(lower(trim(e)), '@', 1);
CREATE OR REPLACE MACRO email_domain(e) AS split_part(lower(trim(e)), '@', 2);

CREATE OR REPLACE MACRO normalize_email(e) AS
    CASE
        WHEN email_domain(e) IN ('gmail.com', 'googlemail.com')
            THEN replace(split_part(email_local(e), '+', 1), '.', '') || '@gmail.com'
        ELSE split_part(email_local(e), '+', 1) || '@' || email_domain(e)
    END;

CREATE OR REPLACE MACRO is_disposable_email(e) AS
    email_domain(e) IN (SELECT domain FROM disposable_domains);

-- Geography -----------------------------------------------------------------
-- Great-circle distance in km between two lat/lon points (haversine formula).
CREATE OR REPLACE MACRO haversine_km(lat1, lon1, lat2, lon2) AS
    2 * 6371.0 * asin(sqrt(
        pow(sin(radians(lat2 - lat1) / 2), 2)
        + cos(radians(lat1)) * cos(radians(lat2)) * pow(sin(radians(lon2 - lon1) / 2), 2)
    ));

-- Implied travel speed between two logins. A floor of 1 minute on elapsed time
-- avoids divide-by-zero when two logins share a timestamp.
CREATE OR REPLACE MACRO travel_speed_kmh(lat1, lon1, ts1, lat2, lon2, ts2) AS
    haversine_km(lat1, lon1, lat2, lon2)
    / greatest(abs(epoch(ts2) - epoch(ts1)) / 3600.0, 1.0 / 60);
