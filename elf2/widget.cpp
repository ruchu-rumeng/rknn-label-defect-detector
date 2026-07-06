#include "widget.h"
#include "ui_widget.h"
#include <opencv2/opencv.hpp>
#include <QJsonDocument>
#include <QJsonObject>
#include <QVBoxLayout>
#include <QHeaderView>
#include <QMouseEvent>
#include <QFile>

// ===== MQTT 配置（部署时修改）=====
#define MQTT_BROKER_HOST  "192.168.137.1"  // 上位机 IP 地址
#define MQTT_BROKER_PORT  1883              // MQTT Broker 端口
#define MQTT_DEVICE_ID    "elf2-line01"    // 设备唯一标识（产线编号）

Widget::Widget(QWidget *parent) :
    QWidget(parent),
    ui(new Ui::Widget)
{
    ui->setupUi(this);
    ui->jsonLog->installEventFilter(this);
    connect(ui->historyBtn, &QPushButton::clicked, this, &Widget::showHistoryDialog);
    connect(ui->camSwitchBtn, &QPushButton::clicked, this, &Widget::onToggleCamera);
    initCameraThread(21);  // 默认启动 USB 摄像头
    initInferenceThread();

    // ===== GPIO 外部触发配置 =====
    // GPIO 139：请在终端先执行以下命令配置
    //   echo 139 > /sys/class/gpio/export
    //   echo in > /sys/class/gpio/gpio139/direction
    // 如果悬空时 value=1，说明内部上拉使能，需要外接下拉电阻或改代码逻辑
    gpioPath = "/sys/class/gpio/gpio139/value";

    gpioTimer = new QTimer(this);
    connect(gpioTimer, &QTimer::timeout, this, &Widget::checkGpio);
    gpioTimer->start(50);  // 每 50ms 读一次 GPIO
}

void Widget::initCameraThread(int index)
{
    m_thread = new QThread(this);
    cameraThread = new CameraThread(index);
    cameraThread->moveToThread(m_thread);
    connect(cameraThread, &CameraThread::frameReady, this, &Widget::onFrameReady);
    connect(cameraThread, &CameraThread::fpsUpdated, this, &Widget::onFpsUpdated);
    connect(m_thread, &QThread::started, cameraThread, &CameraThread::startCapture);
    m_thread->start();
}

void Widget::onToggleCamera()
{
    // 1. 停止推理并等待其线程退出
    if (inferenceThread) inferenceThread->stop();
    if (m_inferThread) {
        m_inferThread->quit();
        m_inferThread->wait(3000);
    }

    // 2. 停止摄像头并等待其线程退出
    if (cameraThread) cameraThread->stop();
    if (m_thread) {
        m_thread->quit();
        m_thread->wait(3000);
    }

    // 3. 删除旧对象
    delete inferenceThread;
    inferenceThread = nullptr;
    delete cameraThread;
    cameraThread = nullptr;
    delete m_inferThread;
    m_inferThread = nullptr;
    delete m_thread;
    m_thread = nullptr;

    // 4. 切换
    useUsb = !useUsb;
    int newIndex = useUsb ? 21 : 11;

    // 5. 重建摄像头
    m_thread = new QThread(this);
    cameraThread = new CameraThread(newIndex);
    cameraThread->moveToThread(m_thread);
    connect(cameraThread, &CameraThread::frameReady, this, &Widget::onFrameReady);
    connect(cameraThread, &CameraThread::fpsUpdated, this, &Widget::onFpsUpdated);
    connect(m_thread, &QThread::started, cameraThread, &CameraThread::startCapture);
    m_thread->start();

    // 6. 重建推理
    m_inferThread = new QThread(this);
    inferenceThread = new InferenceThread();
    inferenceThread->setCameraThread(cameraThread);
    if (!inferenceThread->initModels(
        "/home/elf/qt_ws/hello/model/detector_best.rknn",
        "/home/elf/qt_ws/hello/model/classifier_best.rknn")) {
        return;
    }
    inferenceThread->moveToThread(m_inferThread);
    connect(inferenceThread, &InferenceThread::resultReady, this, &Widget::onResultReady);
    connect(inferenceThread, &InferenceThread::logReady, this, &Widget::onLogReady);
    connect(m_inferThread, &QThread::started, inferenceThread, &InferenceThread::start);
    m_inferThread->start();

    ui->camSwitchBtn->setText(useUsb ? "切换摄像头 (CSI)" : "切换摄像头 (USB)");
}

void Widget::checkGpio()
{
    // 读取 GPIO 电平值
    QFile f(gpioPath);
    if (!f.open(QIODevice::ReadOnly)) return;
    QByteArray data = f.readAll();
    f.close();

    int state = (data.trimmed() == "1") ? 1 : 0;

    // 下降沿检测
    if (lastGpioState == 1 && state == 0) {
        // 触发一次推理（通过事件队列投递到推理线程执行）
        if (inferenceThread) {
            QMetaObject::invokeMethod(inferenceThread, "doInference", Qt::QueuedConnection);
        }
    }
    lastGpioState = state;
}

void Widget::onFrameReady(QImage image)
{
    QPixmap pixmap = QPixmap::fromImage(image);
    pixmap = pixmap.scaled(ui->videoLabel->size(), Qt::KeepAspectRatio, Qt::FastTransformation);
    ui->videoLabel->setPixmap(pixmap);
    ui->videoLabel->setStyleSheet("background-color: black;");
}

void Widget::initInferenceThread()
{
    m_inferThread = new QThread(this);
    inferenceThread = new InferenceThread();
    inferenceThread->setCameraThread(cameraThread);

    // ===== MQTT 初始化（异步连接，不阻塞 UI）=====
    mqttClient = new MqttClient(this);
    mqttClient->connectBroker(MQTT_BROKER_HOST, MQTT_BROKER_PORT, MQTT_DEVICE_ID);  // 后台尝试连接，失败也不阻塞
    inferenceThread->setMqttClient(mqttClient);

    if (!inferenceThread->initModels(
        "/home/elf/qt_ws/hello/model/detector_best.rknn",
        "/home/elf/qt_ws/hello/model/classifier_best.rknn")) {
        return;
    }

    inferenceThread->moveToThread(m_inferThread);
    connect(inferenceThread, &InferenceThread::resultReady, this, &Widget::onResultReady);
    connect(inferenceThread, &InferenceThread::logReady, this, &Widget::onLogReady);
    connect(m_inferThread, &QThread::started, inferenceThread, &InferenceThread::start);
    m_inferThread->start();

    // ===== MQTT 心跳定时器（5秒一次）=====
    hbTimer = new QTimer(this);
    connect(hbTimer, &QTimer::timeout, this, [this]() {
        if (mqttClient && mqttClient->isConnected()) {
            QString hbTopic = QString("elf2/%1/heartbeat").arg(deviceId);
            mqttClient->publish(hbTopic, "alive");
        }
    });
    hbTimer->start(5000);
}

void Widget::onResultReady(const DetectionResult &result)
{
    cv::Mat rgbResult;
    cv::cvtColor(result.resultImage, rgbResult, cv::COLOR_BGR2RGB);
    QImage img(rgbResult.data, rgbResult.cols, rgbResult.rows, rgbResult.step, QImage::Format_RGB888);
    QPixmap pixmap = QPixmap::fromImage(img.copy());
    pixmap = pixmap.scaled(ui->resultLabel->size(), Qt::KeepAspectRatio, Qt::FastTransformation);
    ui->resultLabel->setPixmap(pixmap);

    ui->gradeValue->setText(QString::number(result.grade));
    ui->defectValue->setText(result.defect);
    ui->offsetValue->setText(result.positionOk ? "否" : "是");
}

void Widget::onLogReady(const QString &json)
{
    QJsonDocument doc = QJsonDocument::fromJson(json.toUtf8());
    QJsonObject obj = doc.object();

    HistoryEntry entry;
    entry.id = obj["seq_id"].toInt();
    entry.time = obj["timestamp"].toString();
    entry.grade = obj["grade"].toInt();
    entry.defect = obj["defect"].toString();
    entry.positionOk = obj["position_ok"].toBool();
    history.append(entry);

    QString display = QString("[%1] %2 | Grade:%3 Defect:%4 偏移:%5")
        .arg(entry.id)
        .arg(entry.time)
        .arg(entry.grade)
        .arg(entry.defect)
        .arg(entry.positionOk ? "否" : "是");
    ui->jsonLog->setText(display);
}

void Widget::onFpsUpdated(int fps)
{
    ui->fpsLabel->setText(QString("FPS: %1").arg(fps));
}

bool Widget::eventFilter(QObject *obj, QEvent *event)
{
    if (obj == ui->jsonLog && event->type() == QEvent::MouseButtonPress) {
        showHistoryDialog();
        return true;
    }
    return QWidget::eventFilter(obj, event);
}

void Widget::showHistoryDialog()
{
    if (!historyDialog) {
        historyDialog = new QDialog(this);
        historyDialog->setWindowTitle("推理数据回溯");
        historyDialog->resize(600, 400);

        QVBoxLayout *layout = new QVBoxLayout(historyDialog);
        historyTable = new QTableWidget(historyDialog);
        historyTable->setColumnCount(5);
        historyTable->setHorizontalHeaderLabels(QStringList() << "ID" << "时间" << "等级" << "缺陷" << "偏移");
        historyTable->horizontalHeader()->setStretchLastSection(true);
        historyTable->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
        historyTable->setSelectionBehavior(QAbstractItemView::SelectRows);
        historyTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
        layout->addWidget(historyTable);
    }

    historyTable->setRowCount(history.size());
    for (int i = 0; i < history.size(); i++) {
        const HistoryEntry &e = history[i];
        historyTable->setItem(i, 0, new QTableWidgetItem(QString::number(e.id)));
        historyTable->setItem(i, 1, new QTableWidgetItem(e.time));
        historyTable->setItem(i, 2, new QTableWidgetItem(QString::number(e.grade)));
        historyTable->setItem(i, 3, new QTableWidgetItem(e.defect));
        historyTable->setItem(i, 4, new QTableWidgetItem(e.positionOk ? "否" : "是"));
    }
    historyTable->scrollToBottom();
    historyDialog->show();
    historyDialog->raise();
    historyDialog->activateWindow();
}

Widget::~Widget()
{
    if (hbTimer) {
        hbTimer->stop();
        delete hbTimer;
    }
    if (mqttClient) mqttClient->disconnectBroker();
    if (inferenceThread) inferenceThread->stop();
    if (m_inferThread) {
        m_inferThread->quit();
        m_inferThread->wait(3000);
    }
    if (cameraThread) cameraThread->stop();
    if (m_thread) {
        m_thread->quit();
        m_thread->wait(3000);
    }
    delete inferenceThread;
    delete m_inferThread;
    delete cameraThread;
    delete m_thread;
    delete mqttClient;
    delete ui;
}
