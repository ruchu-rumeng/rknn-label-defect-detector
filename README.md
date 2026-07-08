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
| 触发 IO | GPIO4_B3(瑞芯微的命名格式,GPIO139) |
| 网络 | 与 MQTT Broker 同局域网 |

## 软件依赖
用到了OpenCV库以及MQTT
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

## GPIO 自启动服务（可选）

如果你使用 GPIO139 作为外部触发输入，建议配置 systemd 开机自启动服务，避免每次重启后手动 export GPIO：

```bash
# 1. 复制脚本和服务文件到系统目录
sudo cp elf2/gpio/gpioinit.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/gpioinit.sh
sudo cp elf2/gpio/gpio139.service /etc/systemd/system/

# 2. 启用并启动服务
sudo systemctl daemon-reload
sudo systemctl enable gpio139.service
sudo systemctl start gpio139.service

# 3. 验证
sudo systemctl status gpio139.service
cat /sys/class/gpio/gpio139/direction   
```

**文件说明：**

| 文件 | 说明 |
|------|------|
| `elf2/gpio/gpioinit.sh` | 安全导出 GPIO139 并设为输入；已导出则跳过；放宽权限便于程序访问 |
| `elf2/gpio/gpio139.service` | systemd oneshot 类型服务，开机自动执行脚本，不常驻内存 |

**注意事项：**
- GPIO139 对应 RK3588 的 GPIO4_B4（瑞芯微命名）
- 脚本已做幂等处理：重复 `enable` 不会报错
- `chmod 777` 是为了让非 root 用户运行的 Qt 程序也能读写 GPIO

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

---

## 上位机管理系统（PC Software）

`host_software/` 目录包含基于 PyQt6 + MQTT 的上位机管理软件，用于接收、存储、展示和分析 ELF2 开发板的检测数据。

### 功能特性

- **实时监控看板**：在线设备列表、检测统计卡片、最新记录表格、报警警示条
- **数据存储**：SQLite 本地持久化，支持按时间/设备/缺陷类型筛选
- **历史查询与导出**：导出 CSV / Excel 报告
- **可视化分析**：matplotlib 每小时/每日趋势、缺陷饼图、良率柱状图
- **设备管理**：在线状态监控、远程命令下发（trigger_detect / set_threshold 等）
- **报警系统**：等级阈值/缺陷类型/偏移超标触发，界面警示条 + 声音
- **MQTT Broker 自动启动**：程序自动检测并启动 mosquitto，产线开箱即用
- **调试信息面板**：实时显示 MQTT 连接状态、Broker 地址、最后消息时间
- **日志系统**：自动写入 `data/logs/app.log`，支持内存缓存最近 200 条

### 上位机项目结构

```
host_software/
├── config/                 # 配置层
│   ├── settings.py         # 系统配置管理（JSON 持久化）
│   └── mqtt_topic_spec.md  # MQTT Topic 设计规范
├── core/                   # 业务核心层
│   ├── mqtt_client.py      # MQTT 客户端（paho-mqtt + 自动重连）
│   ├── broker_manager.py   # MQTT Broker 自动检测/启动/关闭
│   ├── data_processor.py   # 数据校验与处理器
│   └── alarm_manager.py    # 报警规则引擎
├── database/               # 数据层
│   ├── schema.sql          # SQLite 数据库 DDL
│   └── db_manager.py       # 数据库管理器（单例）
├── ui/                     # UI 层（PyQt6）
│   ├── main_window.py      # 主窗口（侧边栏导航）
│   ├── dashboard.py        # 实时监控看板 + 调试面板
│   ├── device_manager.py   # 设备管理页面
│   ├── history_view.py     # 历史查询与导出
│   ├── analytics.py        # 统计分析（matplotlib）
│   └── settings_dialog.py  # 系统设置对话框
├── utils/                  # 工具层
│   ├── logger.py           # 日志文件系统
│   ├── validators.py       # 数据校验
│   ├── image_utils.py      # Base64 图片处理
│   └── export_utils.py     # CSV/Excel 导出
├── main.py                 # 入口文件（自动启动 Broker）
├── requirements.txt        # Python 依赖
├── build.py                # PyInstaller 打包脚本
└── README.md               # 本文件
```

### 快速开始

```bash
# 安装依赖
pip install -r host_software/requirements.txt

# 运行
python host_software/main.py

# 打包为可执行文件
python host_software/build.py
# 输出: dist/IPC_Monitor_System.exe
```

### 产线部署（MQTT Broker 自动启动）

1. **首次运行**：下载安装 [mosquitto](https://mosquitto.org/download/)
2. **打开系统设置** → 勾选"自动启动本地 mosquitto"
3. **配置路径**：如 `C:\Program Files\mosquitto\mosquitto.exe`
4. **确定保存**，重启程序

之后每次双击 `IPC_Monitor_System.exe` 都会自动启动 mosquitto（配置 `listener 1883 0.0.0.0`，监听所有接口），开发板只需连接 PC 的 IP 即可。

### 调试方法

看板底部展开「调试信息」面板，实时显示：
- MQTT 连接状态（已连接/未连接）
- Broker 地址和端口
- 订阅的 topic
- 最后收到消息的时间和内容

日志文件：`data/logs/app.log`

### 开发板对接注意事项

- MQTT Broker 地址必须配为 **PC 的 IP**（如 `192.168.137.1`），不能是 `127.0.0.1`
- JSON 字段名必须对齐：`seq_id`、`timestamp`、`device_id`、`position_ok`
- 检测数据 QoS 建议改为 1（防止网络抖动丢数据）
- 需要定时发送心跳到 `elf2/{device_id}/heartbeat`（5秒一次）

详见 `host_software/embedded_changes.md` 和 `host_software/config/mqtt_topic_spec.md`

## 许可证

MIT License
