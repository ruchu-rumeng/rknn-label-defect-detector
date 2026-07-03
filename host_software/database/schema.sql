-- ============================================
-- 工业标签缺陷检测上位机系统 - 数据库 DDL
-- SQLite / MySQL 兼容
-- ============================================

-- --------------------------------------------------------
-- 1. 设备表 (devices)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT    NOT NULL UNIQUE,         -- 设备唯一标识, e.g. "elf2-line01"
    name          TEXT    NOT NULL DEFAULT '',       -- 设备显示名称
    group_name    TEXT    NOT NULL DEFAULT '默认产线', -- 所属产线/分组
    location      TEXT    DEFAULT '',               -- 物理位置描述
    mqtt_topic    TEXT    NOT NULL DEFAULT '',       -- 订阅的检测 topic
    cmd_topic     TEXT    DEFAULT '',               -- 命令下发 topic
    status        TEXT    NOT NULL DEFAULT 'offline', -- online / offline / error
    last_heartbeat TIMESTAMP,                        -- 最后心跳时间
    total_count   INTEGER NOT NULL DEFAULT 0,        -- 累计检测数
    ok_count      INTEGER NOT NULL DEFAULT 0,        -- 良品数
    ng_count      INTEGER NOT NULL DEFAULT 0,        -- 不良品数
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------
-- 2. 检测结果表 (detection_results)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS detection_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT    NOT NULL,
    timestamp     TEXT    NOT NULL,                  -- "2026-06-30 14:23:05"
    seq_id        INTEGER NOT NULL,                  -- 设备自增序号
    grade         INTEGER NOT NULL DEFAULT 0,        -- 能效等级 1-5, 0=未检测
    defect        TEXT    NOT NULL DEFAULT 'normal', -- normal / damage / stain / wrinkle
    position_ok   INTEGER NOT NULL DEFAULT 1,        -- 1=true, 0=false
    is_ng         INTEGER NOT NULL DEFAULT 0,        -- 1=NG, 0=OK (自动计算)
    alarm_triggered INTEGER DEFAULT 0,               -- 是否触发报警
    raw_json      TEXT,                              -- 原始 JSON 备份
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 3. 报警记录表 (alarms)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS alarms (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT    NOT NULL,
    result_id     INTEGER,                           -- 关联 detection_results.id
    alarm_type    TEXT    NOT NULL,                  -- grade_defect / defect / offset / offline
    alarm_level   TEXT    NOT NULL DEFAULT 'warning', -- warning / critical / info
    message       TEXT    NOT NULL,                  -- 报警内容
    is_read       INTEGER NOT NULL DEFAULT 0,      -- 0=未读, 1=已读
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE,
    FOREIGN KEY (result_id) REFERENCES detection_results(id) ON DELETE SET NULL
);

-- --------------------------------------------------------
-- 4. 系统配置表 (system_settings)
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_settings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    key           TEXT    NOT NULL UNIQUE,
    value         TEXT,
    description   TEXT,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------
-- 5. 设备心跳表 (device_heartbeats) — 可选，用于更精确离线判定
-- --------------------------------------------------------
CREATE TABLE IF NOT EXISTS device_heartbeats (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT    NOT NULL,
    heartbeat_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
);

-- --------------------------------------------------------
-- 索引优化
-- --------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_results_device_time ON detection_results(device_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_results_defect      ON detection_results(defect);
CREATE INDEX IF NOT EXISTS idx_results_is_ng       ON detection_results(is_ng);
CREATE INDEX IF NOT EXISTS idx_results_created     ON detection_results(created_at);
CREATE INDEX IF NOT EXISTS idx_alarms_device       ON alarms(device_id);
CREATE INDEX IF NOT EXISTS idx_alarms_unread       ON alarms(is_read, created_at);
CREATE INDEX IF NOT EXISTS idx_devices_group       ON devices(group_name);
CREATE INDEX IF NOT EXISTS idx_heartbeats_device   ON device_heartbeats(device_id, heartbeat_at);

-- --------------------------------------------------------
-- 默认系统配置插入
-- --------------------------------------------------------
INSERT OR IGNORE INTO system_settings (key, value, description) VALUES
('mqtt_broker_host', '127.0.0.1', 'MQTT Broker 地址'),
('mqtt_broker_port', '1883', 'MQTT Broker 端口'),
('mqtt_username', '', 'MQTT 用户名'),
('mqtt_password', '', 'MQTT 密码'),
('mqtt_use_tls', '0', '是否启用 TLS (0/1)'),
('mqtt_subscribe_topic', 'elf2/+/detect/result', '默认检测数据订阅 topic'),
('mqtt_cmd_topic_template', 'elf2/{device_id}/cmd', '命令下发 topic 模板'),
('mqtt_heartbeat_interval', '30', '心跳超时判定秒数'),
('alarm_sound_enabled', '1', '是否启用报警声音'),
('alarm_popup_enabled', '1', '是否启用报警弹窗'),
('alarm_grade_threshold', '1', '能效等级报警阈值 (>此值触发)'),
('alarm_defect_types', 'damage,stain,wrinkle', '触发报警的缺陷类型'),
('alarm_offset_enabled', '1', '偏移超标是否报警'),
('data_retention_days', '90', '数据自动保留天数 (0=永久)'),
('ui_refresh_interval', '1000', 'UI 刷新间隔 ms'),
('export_dir', './exports', '默认导出目录');
