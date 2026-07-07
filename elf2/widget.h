#ifndef WIDGET_H
#define WIDGET_H

#include <QWidget>
#include <QThread>
#include <QFile>
#include <QDateTime>
#include <QTimer>
#include <QTableWidget>
#include "CameraThread.h"
#include "InferenceThread.h"
#include "MqttClient.h"

namespace Ui {
class Widget;
}

class Widget : public QWidget
{
    Q_OBJECT

public:
    explicit Widget(QWidget *parent = nullptr);
    ~Widget();

private slots:
    void onResultReady(const DetectionResult &result);
    void onLogReady(const QString &json);
    void onCamSwitchClicked();
    void onHistoryClicked();

private:
    Ui::Widget *ui;

    QThread cameraThreadObj;
    CameraThread *cameraThread;

    QThread inferenceThreadObj;
    InferenceThread *inferenceThread;

    MqttClient *mqttClient;

    int camIndex = 0;  // 0=USB, 1=MIPI-CSI
    bool switchingCam = false;

    void rebuildCamera();

    // GPIO 读取
    int lastGpioState = 1;  // 常闭传感器默认高电平
    QTimer *gpioTimer;
    void readGpioState();

    // 蜂鸣器
    void buzzerOn();
    void buzzerOff();
    bool buzzerActive = false;
    QTimer *buzzerTimer;

    // MQTT 心跳
    QTimer *hbTimer;
    void sendHeartbeat();

    // 历史记录
    struct HistoryItem {
        QString time;
        int grade;
        QString defect;
        bool positionOk;
    };
    QVector<HistoryItem> history;
    void showHistoryDialog();
};

#endif // WIDGET_H
