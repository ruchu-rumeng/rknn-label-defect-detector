#ifndef INFERENCETHREAD_H
#define INFERENCETHREAD_H

#include <QObject>
#include <QTimer>
#include <opencv2/opencv.hpp>
#include "RKNNModel.h"

class CameraThread;
class MqttClient;

struct DetectionResult {
    int grade;
    QString defect;
    bool positionOk;
    cv::Mat resultImage;
};

class InferenceThread : public QObject {
    Q_OBJECT

public:
    explicit InferenceThread(QObject *parent = nullptr);
    ~InferenceThread();
    bool initModels(const QString &detectorPath, const QString &classifierPath);
    void setCameraThread(CameraThread *cam);
    void setMqttClient(MqttClient *mqtt);  // 绑定 MQTT 客户端
    void start();
    void stop();

signals:
    void resultReady(const DetectionResult &result);
    void logReady(const QString &json);

public slots:
    void doInference();

private:
    CameraThread *cameraThread;
    MqttClient *mqttClient = nullptr;  // MQTT 客户端指针
    RKNNModel detector;
    RKNNModel classifier;
    bool running;
    QTimer *timer;

    cv::Mat letterbox(const cv::Mat &src, int targetSize,
                      float &scale, int &padTop, int &padLeft);
    std::vector<std::pair<cv::Rect, float>> postProcess(const std::vector<float> &output,
                                      float scale, int padTop, int padLeft,
                                      int origW, int origH);
    float sigmoid(float x) { return 1.0f / (1.0f + expf(-x)); }
    QString getDefectName(int idx);
};

Q_DECLARE_METATYPE(DetectionResult);
#endif
