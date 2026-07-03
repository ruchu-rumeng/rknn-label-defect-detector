#!/bin/bash
# GPIO 139 初始化脚本
# 用于 ELF2 (RK3588) 开发板，开机自动将 GPIO139 配置为输入模式
# 配合 systemd 服务 gpio139.service 使用

GPIO_NUM=139
EXPORT_FILE="/sys/class/gpio/export"
DIRECTION_FILE="/sys/class/gpio/gpio${GPIO_NUM}/direction"

# 如果已导出则跳过，避免重复 export 报错
if [ -d "/sys/class/gpio/gpio${GPIO_NUM}" ]; then
    echo "GPIO ${GPIO_NUM} already exported"
else
    echo ${GPIO_NUM} > ${EXPORT_FILE}
    echo "GPIO ${GPIO_NUM} exported"
    # 等待 sysfs 节点创建
    sleep 0.1
fi

# 配置为输入模式
echo "in" > ${DIRECTION_FILE}
echo "GPIO ${GPIO_NUM} direction set to input"

# 放宽权限，让普通用户（如运行 Qt 程序的用户）可读写 GPIO
chmod -R 777 /sys/class/gpio/gpio${GPIO_NUM} 2>/dev/null || true
