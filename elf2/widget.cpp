#include "widget.h"
#include "ui_widget.h"
#include <QImage>
#include <QDebug>
#include <QDateTime>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>
#include <QHeaderView>
#include <QDialog>
#include <QFile>
#include <QIODevice>

#define GPIO_VALUE    "/sys/class/gpio/gpio139/value"
#define BUZZER_GPIO   "/sys/class/gpio/gpio116/value"

Widget::Widget(QWidget *parent) :
    QWidget(parent),
    ui(new Ui::Widget),
    camIndex(0),
    switchingCam(false)
{
    ui->setupUi(this);

    // ---- 摄像头线程 ----
    cameraThread = new CameraThread(camIndex);
    cameraThread->moveToThread(&cameraThreadObj);
    connect(&cameraThreadObj, &QThread::started, cameraThread, &CameraThread::startCapture);
    connect(cameraThread, &CameraThread::frameReady, this, [this](QImage img) {
        ui->videoLabel->setPixmap(QPixmap::fromImage(img).scaled(
            ui->videoLabel->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
    });
    connect(cameraThread, &CameraThread::fpsUpdated, this, [this](int fps) {
        ui->fpsLabel->setText(QString("FPS: %1 | 检测: %2").arg(fps).arg(detectCount));
    });
    cameraThreadObj.start();

    // ---- 推理线程 ----
    inferenceThread = new InferenceThread();
    inferenceThread->moveToThread(&inferenceThreadObj);
    inferenceThread->setCameraThread(cameraThread);
    connect(inferenceThread, &InferenceThread::resultReady, this, &Widget::onResultReady);
    connect(inferenceThread, &InferenceThread::logReady, this, &Widget::onLogReady);
    inferenceThreadObj.start();

    // 加载模型（路径根据实际部署调整）
    bool ok = inferenceThread->initModels(
        "/home/elf/models/detector.rknn",
        "/home/elf/models/classifier.rknn");
    if (!ok) qDebug() << "模型加载失败，请检查路径";
    inferenceThread->start();

    // ---- MQTT ----
    mqttClient = new MqttClient(this);
    mqttClient->connectBroker("192.168.1.100", 1883, "elf2_client");
    inferenceThread->setMqttClient(mqttClient);

    // ---- UI 信号 ----
    connect(ui->camSwitchBtn, &QPushButton::clicked, this, &Widget::onCamSwitchClicked);
    connect(ui->historyBtn, &QPushButton::clicked, this, &Widget::onHistoryClicked);

    // ---- GPIO 轮询（50ms）----
    gpioTimer = new QTimer(this);
    connect(gpioTimer, &QTimer::timeout, this, &Widget::readGpioState);
    gpioTimer->start(50);

    // ---- 蜂鸣器定时关闭 ----
    buzzerTimer = new QTimer(this);
    buzzerTimer->setSingleShot(true);
    connect(buzzerTimer, &QTimer::timeout, this, &Widget::buzzerOff);

    // ---- MQTT 心跳（5s）----
    hbTimer = new QTimer(this);
    connect(hbTimer, &QTimer::timeout, this, &Widget::sendHeartbeat);
    hbTimer->start(5000);
}

Widget::~Widget()
{
    gpioTimer->stop();
    buzzerTimer->stop();
    hbTimer->stop();

    inferenceThread->stop();
    inferenceThreadObj.quit();
    inferenceThreadObj.wait();

    cameraThread->stop();
    cameraThreadObj.quit();
    cameraThreadObj.wait();

    delete ui;
}

/* ========== 结果显示 ========== */
void Widget::onResultReady(const DetectionResult &result)
{
    // 更新 UI
    ui->gradeValue->setText(QString::number(result.grade));
    ui->defectValue->setText(result.defect);
    ui->offsetValue->setText(result.positionOk ? "否" : "是");

    // 显示结果图
    QImage img(result.resultImage.data, result.resultImage.cols, result.resultImage.rows,
               static_cast<int>(result.resultImage.step), QImage::Format_BGR888);
    ui->resultLabel->setPixmap(QPixmap::fromImage(img).scaled(
        ui->resultLabel->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));

    // 缺陷报警（非 normal 时蜂鸣器 1s）
    if (result.defect != "正常" && !buzzerActive) {
        buzzerOn();
        buzzerTimer->start(1000);
    }

    // 记录历史
    HistoryItem item;
    item.time = QDateTime::currentDateTime().toString("yyyy-MM-dd hh:mm:ss");
    item.grade = result.grade;
    item.defect = result.defect;
    item.positionOk = result.positionOk;
    history.append(item);
    if (history.size() > 1000) history.removeFirst();  // 限制 1000 条
}

/* ========== JSON 日志 ========== */
void Widget::onLogReady(const QString &json)
{
    ui->jsonLog->append(json);
}

/* ========== 摄像头切换 ========== */
void Widget::onCamSwitchClicked()
{
    if (switchingCam) return;
    switchingCam = true;

    camIndex = (camIndex == 0) ? 1 : 0;
    rebuildCamera();
    ui->camSwitchBtn->setText(camIndex == 0 ? "切换摄像头 (USB)" : "切换摄像头 (MIPI)");

    switchingCam = false;
}

void Widget::rebuildCamera()
{
    // 停止旧摄像头
    cameraThread->stop();
    cameraThreadObj.quit();
    cameraThreadObj.wait();

    // 重建
    delete cameraThread;
    cameraThread = new CameraThread(camIndex);
    cameraThread->moveToThread(&cameraThreadObj);
    connect(&cameraThreadObj, &QThread::started, cameraThread, &CameraThread::startCapture);
    connect(cameraThread, &CameraThread::frameReady, this, [this](QImage img) {
        ui->videoLabel->setPixmap(QPixmap::fromImage(img).scaled(
            ui->videoLabel->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
    });
    cameraThreadObj.start();

    // 通知推理线程
    inferenceThread->setCameraThread(cameraThread);
}

/* ========== GPIO 读取 ========== */
void Widget::readGpioState()
{
    QFile file(GPIO_VALUE);
    if (!file.open(QIODevice::ReadOnly)) return;
    QByteArray data = file.readAll();
    file.close();

    int state = data.trimmed().toInt();
    // 下降沿触发（1→0）
    if (lastGpioState == 1 && state == 0) {
        QMetaObject::invokeMethod(inferenceThread, "doInference", Qt::QueuedConnection);
    }
    lastGpioState = state;
}

/* ========== 蜂鸣器 ========== */
void Widget::buzzerOn()
{
    QFile f(BUZZER_GPIO);
    if (f.open(QIODevice::WriteOnly)) {
        f.write("1");
        f.close();
    }
    buzzerActive = true;
}

void Widget::buzzerOff()
{
    QFile f(BUZZER_GPIO);
    if (f.open(QIODevice::WriteOnly)) {
        f.write("0");
        f.close();
    }
    buzzerActive = false;
}

/* ========== MQTT 心跳 ========== */
void Widget::sendHeartbeat()
{
    if (mqttClient && mqttClient->isConnected()) {
        QString ts = QDateTime::currentDateTime().toString("yyyy-MM-dd hh:mm:ss");
        QString json = QString("{\"type\":\"heartbeat\",\"timestamp\":\"%1\"}").arg(ts);
        mqttClient->publish("energy_label/heartbeat", json);
    }
}

/* ========== 历史记录 ========== */
void Widget::onHistoryClicked()
{
    showHistoryDialog();
}

void Widget::showHistoryDialog()
{
    QDialog *dlg = new QDialog(this);
    dlg->setWindowTitle("历史检测记录");
    dlg->resize(600, 400);

    QVBoxLayout *layout = new QVBoxLayout(dlg);
    QTableWidget *table = new QTableWidget(dlg);
    table->setColumnCount(4);
    table->setHorizontalHeaderLabels(QStringList() << "时间" << "等级" << "缺陷" << "偏移");
    table->horizontalHeader()->setStretchLastSection(true);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);

    table->setRowCount(history.size());
    for (int i = 0; i < history.size(); ++i) {
        table->setItem(i, 0, new QTableWidgetItem(history[i].time));
        table->setItem(i, 1, new QTableWidgetItem(QString::number(history[i].grade)));
        table->setItem(i, 2, new QTableWidgetItem(history[i].defect));
        table->setItem(i, 3, new QTableWidgetItem(history[i].positionOk ? "否" : "是"));
    }

    layout->addWidget(table);
    dlg->setLayout(layout);
    dlg->exec();
    delete dlg;
}
