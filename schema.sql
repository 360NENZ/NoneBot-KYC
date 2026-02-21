-- MariaDB schema for real-name authentication
-- qq_id is VARCHAR(64) to support both:
--   - OneBot V11 integer QQ numbers (stored as numeric strings, e.g. "123456789")
--   - QQ Official Bot openid strings (alphanumeric, e.g. "ABC123XYZ")

CREATE DATABASE IF NOT EXISTS auth_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE auth_db;

CREATE TABLE IF NOT EXISTS users (
    qq_id        VARCHAR(64)  NOT NULL,
    real_name    VARCHAR(64)  DEFAULT NULL,
    id_number    CHAR(18)     DEFAULT NULL,
    uid1         VARCHAR(64)  DEFAULT NULL,
    uid2         VARCHAR(64)  DEFAULT NULL,
    uid3         VARCHAR(64)  DEFAULT NULL,
    auth_status  VARCHAR(32)  NOT NULL DEFAULT 'Unverified',
    inviter_id   VARCHAR(64)  DEFAULT NULL,
    invite_count INT          NOT NULL DEFAULT 0,
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (qq_id),
    FOREIGN KEY (inviter_id) REFERENCES users(qq_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create a dedicated DB user for the API server
CREATE USER IF NOT EXISTS 'auth_user'@'%' IDENTIFIED BY 'auth_pass';
GRANT SELECT, INSERT, UPDATE ON auth_db.users TO 'auth_user'@'%';
FLUSH PRIVILEGES;

-- ── Migration note ─────────────────────────────────────────────────────────
-- If upgrading from a previous BIGINT schema, run:
--
--   ALTER TABLE users
--     MODIFY qq_id      VARCHAR(64) NOT NULL,
--     MODIFY inviter_id VARCHAR(64) DEFAULT NULL;
--
-- No data loss occurs because MySQL casts integers to strings automatically.
