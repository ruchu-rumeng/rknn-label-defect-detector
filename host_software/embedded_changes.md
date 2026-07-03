# 嵌入式端对接修改清单（vs 上位机 IPC_Monitor_System）

> 对应上位机版本：删除了 `offset_ratio`、`detector_conf`、`image_base64` 字段

---

## 一、JSON 字段名必须改（P0 — 不改上位机收不到数据）

| 你当前代码 | 应该改成 | 说明 |
|------------|----------|------|
| `"id":15` | `"seq_id":15` | 字段名改为 `seq_id`（整数） |
| `"time":"2026-06-30 14:23:05"` | `"timestamp":"2026-06-30 14:23:05"` | 字段名改为 `timestamp` |
| **缺少** | `"device_id":"elf2-line01"` | 必须添加，用于多设备区分 |
| `"ok":true` | `"position_ok":true` | 字段名改为 `position_ok`（布尔值） |
| `"grade":2` | `"grade":2` | ✅ 正常，1-5 范围 |
| `"defect":"normal"` | `"defect":"normal"` | ✅ 正常，枚举值：normal/damage/stain/wrinkle |

**建议修改后的 JSON 组装代码（InferenceThread.cpp）：**

```cpp
static int s_id = 0;
// 注意：HH 是 24 小时制，hh 是 12 小时制（请用大写 HH）
QString timeStr = QDateTime::currentDateTime().toString("yyyy-MM-dd HH:mm:ss");

QString json = QString(
    "{"
    "\"device_id\":\"elf2-line01\","       // 建议从配置文件读取 device_id
    "\"timestamp\":\"%1\","
    "\"seq_id\":%2,"
    "\"grade\":%3,"
    "\"defect\":\"%4\","
    "\"position_ok\":%5"
    "}"
)
.arg(timeStr)
.arg(++s_id)
.arg(grade)
.arg(getDefectName(defectIdx))
.arg(positionOk ? "true" : "false");

// 发送 topic
QString deviceId = "elf2-line01";   // 建议从配置读取
QString topic = QString("elf2/%1/detect/result").arg(deviceId);
if (mqttClient) {
    mqttClient->publish(topic, json);
}
```

---

## 二、QoS 改为 1（P1 — 防止检测数据丢失）

你当前代码（MqttClient.cpp 第 64 行）：
```cpp
mosquitto_publish(mosq, nullptr, ..., 0, false);  // QoS=0
```

**改为：**
```cpp
int ret = mosquitto_publish(mosq, nullptr,
    topic.toUtf8().constData(),
    payload.toUtf8().size(),
    payload.toUtf8().constData(),
    1,       // <-- QoS 从 0 改为 1
    false);
```

> 检测数据用 QoS 1 确保至少送达一次，心跳保持 QoS 0 即可。

---

## 三、加设备心跳（P1 — 上位机正确显示在线/离线）

上位机默认 30 秒判定超时，如果 60 秒内没收到心跳，设备会被标记为"离线"。

**建议在 widget.cpp 或主线程中加定时器：**

```cpp
// 初始化时
QTimer *hbTimer = new QTimer(this);
connect(hbTimer, &QTimer::timeout, [=]() {
    if (mqttClient && mqttClient->isConnected()) {
        QString hbTopic = QString("elf2/%1/heartbeat").arg(deviceId);
        mqttClient->publish(hbTopic, "alive");  // 任意短内容即可
    }
});
hbTimer->start(5000);  // 5 秒一次
```

---

## 四、device_id 不要硬编码（P2）

当前 `"elf2-line01"` 和 `"elf2/line01/..."` 都是硬编码的。

**建议：** 从配置文件（如 `config.json`）或环境变量读取：

```cpp
// 伪代码
QString deviceId = Config::get("device_id", "elf2-line01");
QString topic = QString("elf2/%1/detect/result").arg(deviceId);
QString cmdTopic = QString("elf2/%1/cmd").arg(deviceId);  // 后续命令下发用
```

这样同一套固件可以在多个设备上运行，只需改配置即可。

---

## 五、可选：命令响应（P3 — 后续扩展用）

上位机可以发送命令到 `elf2/{device_id}/cmd`，如：

```json
{"cmd": "trigger_detect"}
{"cmd": "set_threshold", "params": {"grade": 2}}
```

**如需支持，在 MqttClient 中订阅并处理：**

```cpp
// connectBroker 成功后
mosquitto_subscribe(mosq, nullptr, "elf2/line01/cmd", 1);

// 设置消息回调
mosquitto_message_callback_set(mosq, [](mosquitto*, void*, const mosquitto_message* msg) {
    QString payload = QString::fromUtf8((char*)msg->payload, msg->payloadlen);
    // 解析 JSON，执行 trigger_detect / set_threshold 等
});
```

---

## 修改优先级总结

| 优先级 | 修改项 | 不改的后果 |
|--------|--------|------------|
| **P0** | JSON 字段名对齐（`seq_id`、`timestamp`、`device_id`、`position_ok`） | 上位机校验失败，数据进不了数据库 |
| **P1** | QoS 改为 1 | 网络抖动时可能丢检测数据 |
| **P1** | 加心跳 | 上位机始终显示设备"离线" |
| **P2** | device_id 非硬编码 | 多设备部署时需要改源码重新编译 |
| **P3** | 命令响应 | 无法远程控制设备（后续扩展） |
