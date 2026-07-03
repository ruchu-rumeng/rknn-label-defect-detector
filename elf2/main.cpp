#include "widget.h"
#include <QApplication>
#include <QDir>
#include <QFile>
#include <QIODevice>
#include <QDebug>

#define GPIO          "/sys/class/gpio/gpio139"
#define GPIO_EXPORT   "/sys/class/gpio/export"
#define GPIO_DIRECTION "/sys/class/gpio/gpio139/direction"

static bool InitGPIO();

int main(int argc, char *argv[])
{
    if (!InitGPIO()) {
        printf("[GPIO 警告] 初始化失败，程序继续运行...\n");
    }

    QApplication a(argc, argv);
    qRegisterMetaType<DetectionResult>();
    Widget w;
    w.show();

    return a.exec();
}

static bool InitGPIO()
{
    if (!QDir(GPIO).exists()) {
        QFile exp(GPIO_EXPORT);
        if (!exp.open(QIODevice::WriteOnly)) {
            printf("[GPIO 错误] 无法打开 %s，需要 root 权限\n", GPIO_EXPORT);
            return false;
        }
        if (exp.write("139\n") == -1) {
            printf("[GPIO 错误] 导出 GPIO 139 失败\n");
            return false;
        }
        exp.close();
    }

    QFile dir(GPIO_DIRECTION);
    if (!dir.open(QIODevice::WriteOnly)) {
        printf("[GPIO 错误] 无法打开 %s，需要 root 权限\n", GPIO_DIRECTION);
        return false;
    }
    if (dir.write("in\n") == -1) {
        printf("[GPIO 错误] 设置方向为 in 失败\n");
        return false;
    }
    dir.close();

    printf("[GPIO 成功] GPIO 139 已配置为输入模式\n");
    return true;
}
