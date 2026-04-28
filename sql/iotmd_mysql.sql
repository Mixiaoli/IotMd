-- IotMd MySQL 初始化脚本
-- 用法：mysql -u root -p < sql/iotmd_mysql.sql

CREATE DATABASE IF NOT EXISTS `iotmd`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `iotmd`;

CREATE TABLE IF NOT EXISTS `users` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(64) NOT NULL,
  `password_hash` VARCHAR(256) NOT NULL,
  `is_admin` TINYINT(1) NOT NULL DEFAULT 0,
  `can_use_ai` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_users_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `model_configs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(128) NOT NULL,
  `provider` VARCHAR(64) NOT NULL DEFAULT 'openai-compatible',
  `base_url` VARCHAR(256) NOT NULL DEFAULT '',
  `api_key` VARCHAR(256) NOT NULL DEFAULT '',
  `is_active` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_model_configs_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `question_records` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT NOT NULL,
  `question` TEXT NOT NULL,
  `answer` TEXT NOT NULL,
  `model_name` VARCHAR(128) NOT NULL DEFAULT 'default-model',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_question_records_user_id` (`user_id`),
  KEY `idx_question_records_created_at` (`created_at`),
  CONSTRAINT `fk_question_records_user_id`
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 默认模型配置（如果不存在）
INSERT INTO `model_configs` (`name`, `provider`, `base_url`, `api_key`, `is_active`)
SELECT 'default-model', 'mock', '', '', 1
WHERE NOT EXISTS (
  SELECT 1 FROM `model_configs` WHERE `name` = 'default-model'
);

-- 如需创建管理员，请先用后端 hash_password 逻辑生成 password_hash 再插入：
-- INSERT INTO users(username, password_hash, is_admin, can_use_ai)
-- VALUES ('admin', '替换为真实hash', 1, 1);
