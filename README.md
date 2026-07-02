# 基于elf2开发版的能效标签缺陷检测系统

基于 elf2-RK3588 的工业标签缺陷检测系统，支持 USB/CSI 摄像头、GPIO 外部触发、MQTT 数据上报。

## 功能特性

- **实时检测**：640×480 图像采集，RKNN NPU 推理（Detector + Classifier 双模型）
- **双模型架构**：YOLOv8 检测器定位标签 + MobileNetV3 分类器判定缺陷
- **GPIO 触发**：支持外部 IO 信号触发单帧检测（上升沿检测）
- **MQTT 上报**：检测结果通过 MQTT 协议上报上位机，支持心跳保活
- **摄像头切换**：支持 USB 和 MIPI-CSI 摄像头一键切换
- **USB摄像头畸变矫正**：内置摄像头标定参数，支持 lens distortion 矫正
- **本地 UI**：Qt 实时预览 + 结果展示 + 历史数据回溯

## 硬件要求

| 项目 | 要求 |
|------|------|
| 开发板 | RK3588（ELF 2 开发板） |
| 摄像头 | USB 摄像头（轮趣C70）或 MIPI-CSI（OV13855） |
| 触发 IO | GPIO4_B4(瑞芯微的命名格式,GPIO139) |
| 网络 | 与 MQTT Broker 同局域网 |

## 软件依赖

```bash
sudo apt-get install libopencv-dev libmosquitto-dev qtbase5-dev
```

## 编译
配置了一个简单的编译sh脚本clean_working.sh,包括:清除build的文件,重新make,运行
```bash
mkdir -p build/
qmake
cd ..
chmod +x clean_working.sh
./clean_working.sh
```

## 运行
如果不想用clean_working.sh运行也可以单独运行
```bash
./hello -platform eglfs
```

## 配置
修改 `widget.cpp` 和 `InferenceThread.cpp` 开头的宏定义：
```cpp
#define MQTT_BROKER_HOST  "192.168.137.1"  // 上位机 IP
#define MQTT_BROKER_PORT  1883
#define MQTT_DEVICE_ID    "elf2-line01"    // 产线编号
```

## 模型

- `detector_best.rknn`：YOLOv8n 检测器，输入 640×640，输出 [1,5,8400]
- `classifier_best.rknn`：MobileNetV3 分类器，输入 320×320，输出 5 grade + 4 defect

模型路径在 `widget.cpp` 的 `initInferenceThread()` 中配置。

## MQTT Topic

| Topic | 方向 | 说明 |
|-------|------|------|
| `elf2/{device_id}/detect/result` | 设备→上位机 | 检测结果（JSON） |
| `elf2/{device_id}/heartbeat` | 设备→上位机 | 心跳（5秒一次） |

## 检测输出 JSON

```json
{
  "device_id": "elf2-line01",
  "timestamp": "2026-06-30 14:23:05",
  "seq_id": 15,
  "grade": 2,
  "defect": "normal",
  "position_ok": true
}
```

## 许可证

MIT License
