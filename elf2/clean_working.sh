#!/bin/bash
# 清除 Qt 编译产物
# 清除后运行
set -e

BUILD_DIR="/home/elf/qt_ws/hello/build"

cd "${BUILD_DIR}"
make clean
rm -rf "${BUILD_DIR}/hello"
make 
chmod +x hello
./hello -platform eglfs
#sudo chvt 1
