#ifndef WIDGET_H
#define WIDGET_H

#include <QWidget>
#include <QThread>
#include <QDialog>
#include <QTableWidget>
#include <opencv2/opencv.hpp>
#include "CameraThread.h"
#include "InferenceThread.h"
#include "MqttClient.h"

namespace Ui {
class Widget;
}

struct HistoryEntry {
    int id;
    QString time;
    int grade;
    QString defect;
    bool positionOk;
};

class Widget : public QWidget
{
    Q_OBJECT

public:
    explicit Widget(QWidget *parent = nullptr);
    ~Widget();

protected:
    bool eventFilter(QObject *obj, QEvent *event) override;

private slots:
    void onFrameReady(QImage image);
    void onFpsUpdated(int fps);
    void onResultReady(const DetectionResult &result);
    void onLogReady(const QString &json);
    void onToggleCamera();
    void checkGpio();  // 定时检查 GPIO 状态（外部触发）

private:
    Ui::Widget *ui;
    QThread *m_thread;
    CameraThread *cameraThread;
    QThread *m_inferThread;
    InferenceThread *inferenceThread;
    MqttClient *mqttClient = nullptr;  // MQTT 客户端
    bool useUsb = false;

    QVector<HistoryEntry> history;
    QDialog *historyDialog = nullptr;
    QTableWidget *historyTable = nullptr;

    // GPIO 外部触发相关
    QTimer *gpioTimer = nullptr;
    int lastGpioState = 0;
    QString gpioPath;  // GPIO 文件路径，如 /sys/class/gpio/gpio139/value

    // 蜂鸣器
    bool buzzerActive = false;
    void buzzerOn();
    void buzzerOff();
    
    // MQTT 心跳相关
    QTimer *hbTimer = nullptr;
    QString deviceId = "elf2-line01";  // TODO: 后续从配置文件读取

    void initCameraThread(int index);
    void initInferenceThread();
    void showHistoryDialog();
};

#endif
