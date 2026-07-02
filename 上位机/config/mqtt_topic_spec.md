"""
MQTT Topic 设计规范
===================

一、检测数据上报 (Device → Server)
-----------------------------------
Topic:  elf2/{device_id}/detect/result
Payload: JSON

例:
  elf2/elf2-line01/detect/result
  elf2/elf2-line02/detect/result

消息格式:
{
  "device_id": "elf2-line01",
  "timestamp": "2026-06-30 14:23:05",
  "seq_id": 15,
  "grade": 2,
  "defect": "normal",
  "position_ok": true
}

二、心跳/状态上报 (Device → Server)
------------------------------------
Topic:  elf2/{device_id}/heartbeat
Payload: 任意短文本，或 JSON {"status": "running"}

三、命令下发 (Server → Device)
-------------------------------
Topic:  elf2/{device_id}/cmd
Payload: JSON

支持的命令类型:
1. 修改检测阈值
   {"cmd": "set_threshold", "params": {"grade": 2, "offset_max": 0.08}}

2. 触发单次检测
   {"cmd": "trigger_detect"}

3. 重启设备推理线程
   {"cmd": "restart_inference"}

4. 更新设备参数
   {"cmd": "update_param", "params": {"exposure": 120, "gain": 1.5}}

5. 请求设备状态
   {"cmd": "get_status"}

四、设备响应 (Device → Server，可选)
--------------------------------------
Topic:  elf2/{device_id}/cmd/resp
Payload: JSON
{
  "cmd": "trigger_detect",
  "status": "ok",
  "msg": "检测已触发"
}

五、Topic 订阅规则（服务器端）
-------------------------------
- 使用通配符 + 订阅所有设备检测结果:
    elf2/+/detect/result
- 使用通配符 + 订阅所有设备心跳:
    elf2/+/heartbeat
- 命令响应同样可用通配符:
    elf2/+/cmd/resp

六、QoS 建议
------------
- 检测数据:  QoS 1 (至少一次，确保不丢)
- 心跳:      QoS 0 (允许丢失)
- 命令下发:  QoS 1 (确保到达)
- 命令响应:  QoS 1

七、保留消息 (Retain)
--------------------
- 设备状态/心跳: 可设为 Retain，便于服务器重启后立知设备在线状态
- 检测数据:  不建议 Retain，避免旧数据误报

八、TLS/SSL 配置（可选）
------------------------
- 端口: 8883 (标准 MQTT over TLS)
- 证书: 服务器需配置 ca.crt / server.crt / server.key
- 客户端: 提供对应的 client.crt (如双向认证) 或仅校验服务端证书
"""
