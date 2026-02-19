-- MariaDB schema for real-name authentication
CREATE DATABASE IF NOT EXISTS auth_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE auth_db;

CREATE TABLE IF NOT EXISTS users (
    qq_id       BIGINT PRIMARY KEY,
    real_name   VARCHAR(64)  DEFAULT NULL,
    id_number   CHAR(18)     DEFAULT NULL,
    uid1        VARCHAR(64)  DEFAULT NULL,
    uid2        VARCHAR(64)  DEFAULT NULL,
    uid3        VARCHAR(64)  DEFAULT NULL,
    auth_status VARCHAR(32)  NOT NULL DEFAULT 'Unverified',
    inviter_id  BIGINT       DEFAULT NULL,
    invite_count INT         NOT NULL DEFAULT 0,
    created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (inviter_id) REFERENCES users(qq_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create a DB user for the API
CREATE USER IF NOT EXISTS 'auth_user'@'%' IDENTIFIED BY 'auth_pass';
GRANT SELECT, INSERT, UPDATE ON auth_db.users TO 'auth_user'@'%';
FLUSH PRIVILEGES;
