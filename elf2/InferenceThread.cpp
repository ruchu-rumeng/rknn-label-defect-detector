#include "InferenceThread.h"
#include "CameraThread.h"
#include "MqttClient.h"
#include <QDebug>
#include <QDateTime>
#include <cmath>

// 检测标签名（与训练时的 data.yaml 顺序一致）
static const char* LABEL_NAMES[] = {
    "能效标签", "污渍标签", "破损标签", "能效等级1", "能效等级2",
    "能效等级3", "能效等级4", "能效等级5", "位置偏移", "模糊标签"
};

InferenceThread::InferenceThread(QObject *parent)
    : QObject(parent), cameraThread(nullptr), running(false), timer(nullptr)
{
}

InferenceThread::~InferenceThread()
{
    stop();
}

bool InferenceThread::initModels(const QString &detectorPath, const QString &classifierPath)
{
    if (!detector.load(detectorPath.toStdString())) {
        qDebug() << "Detector 模型加载失败:" << detectorPath;
        return false;
    }
    qDebug() << "Detector 输入尺寸:" << detector.getInputW() << "x" << detector.getInputH();

    if (!classifier.load(classifierPath.toStdString())) {
        qDebug() << "Classifier 模型加载失败:" << classifierPath;
        return false;
    }
    qDebug() << "Classifier 输入尺寸:" << classifier.getInputW() << "x" << classifier.getInputH();

    return true;
}

void InferenceThread::setCameraThread(CameraThread *cam)
{
    cameraThread = cam;
}

void InferenceThread::setMqttClient(MqttClient *mqtt)
{
    mqttClient = mqtt;
}

void InferenceThread::start()
{
    running = true;
}

void InferenceThread::stop()
{
    running = false;
}

/* ========== Letterbox ========== */
cv::Mat InferenceThread::letterbox(const cv::Mat &src, int targetSize,
                                   float &scale, int &padTop, int &padLeft)
{
    int origW = src.cols, origH = src.rows;
    scale = std::min((float)targetSize / origW, (float)targetSize / origH);
    int newW = (int)(origW * scale);
    int newH = (int)(origH * scale);

    padLeft = (targetSize - newW) / 2;
    padTop  = (targetSize - newH) / 2;

    cv::Mat resized, padded(targetSize, targetSize, CV_8UC3, cv::Scalar(114,114,114));
    cv::resize(src, resized, cv::Size(newW, newH), 0, 0, cv::INTER_LINEAR);
    resized.copyTo(padded(cv::Rect(padLeft, padTop, newW, newH)));
    return padded;
}

/* ========== 后处理（简化版 NMS） ========== */
std::vector<std::pair<cv::Rect, float>> InferenceThread::postProcess(
    const std::vector<float> &output,
    float scale, int padTop, int padLeft,
    int origW, int origH)
{
    const float confThreshold = 0.25f;
    const float nmsThreshold  = 0.50f;
    const int   numClasses    = 10;

    std::vector<std::pair<cv::Rect, float>> boxes;
    std::vector<float>                      confs;

    // output 形状: 84 x numAnchors  (YOLOv8 OBB / 标准头)
    int rows = output.size() / (4 + numClasses);
    for (int i = 0; i < rows; ++i) {
        const float *row = output.data() + i * (4 + numClasses);
        float cx = row[0], cy = row[1], w = row[2], h = row[3];

        // 找最大类别置信度
        float bestConf = 0;
        for (int c = 0; c < numClasses; ++c) {
            float v = row[4 + c];
            if (v > bestConf) bestConf = v;
        }
        if (bestConf < confThreshold) continue;

        // 还原到原图坐标
        float x1 = (cx - w/2 - padLeft) / scale;
        float y1 = (cy - h/2 - padTop ) / scale;
        float x2 = (cx + w/2 - padLeft) / scale;
        float y2 = (cy + h/2 - padTop ) / scale;

        x1 = std::max(0.0f, std::min(x1, (float)origW));
        y1 = std::max(0.0f, std::min(y1, (float)origH));
        x2 = std::max(0.0f, std::min(x2, (float)origW));
        y2 = std::max(0.0f, std::min(y2, (float)origH));

        boxes.emplace_back(cv::Rect(cv::Point((int)x1, (int)y1),
                                    cv::Point((int)x2, (int)y2)), bestConf);
        confs.push_back(bestConf);
    }

    // 简单 NMS
    std::vector<int> indices;
    cv::dnn::NMSBoxes(boxes, confs, confThreshold, nmsThreshold, indices);

    std::vector<std::pair<cv::Rect, float>> result;
    for (int idx : indices) result.push_back(boxes[idx]);
    return result;
}

/* ========== 缺陷名称映射 ========== */
QString InferenceThread::getDefectName(int idx)
{
    if (idx >= 0 && idx < 10) return QString::fromUtf8(LABEL_NAMES[idx]);
    return "未知";
}

/* ========== 推理入口 ========== */
void InferenceThread::doInference()
{
    if (!cameraThread) return;

    cv::Mat origFrame = cameraThread->getCurrentFrame();
    if (origFrame.empty()) {
        qDebug() << "未获取到帧";
        return;
    }

    // ---------- Detector ----------
    float scale; int padTop, padLeft;
    cv::Mat detInput = letterbox(origFrame, detector.getInputW(), scale, padTop, padLeft);

    if (!detector.inference(detInput)) {
        qDebug() << "Detector 推理失败";
        return;
    }
    std::vector<float> detOutput = detector.getOutput();

    auto boxes = postProcess(detOutput, scale, padTop, padLeft,
                             origFrame.cols, origFrame.rows);
    if (boxes.empty()) {
        qDebug() << "未检测到标签";
        return;
    }

    // 取置信度最高的框
    cv::Rect bestBox = boxes[0].first;

    // 在图中画出检测框（绿色）
    cv::Mat display = origFrame.clone();
    cv::rectangle(display, bestBox, cv::Scalar(0, 255, 0), 2);

    // ---------- Classifier ----------
    // 从原图裁出检测框区域，直接 resize 到 320x320
    // 注意：Classifier 期望 uint8 RGB NHWC，mean/std 已 bake 进 RKNN
    cv::Mat roi = origFrame(bestBox);
    cv::Mat clsInput;
    cv::resize(roi, clsInput, cv::Size(classifier.getInputW(), classifier.getInputH()),
               0, 0, cv::INTER_LINEAR);

    if (!classifier.inference(clsInput)) {
        qDebug() << "Classifier 推理失败";
        return;
    }
    std::vector<float> clsOutput = classifier.getOutput();

    // 解析分类结果
    int bestIdx = 0;
    float bestProb = clsOutput[0];
    for (size_t i = 1; i < clsOutput.size(); ++i) {
        if (clsOutput[i] > bestProb) {
            bestProb = clsOutput[i];
            bestIdx  = (int)i;
        }
    }

    int    grade   = bestIdx + 1;                     // 等级 1~5
    QString defect = (bestIdx < 5) ? "正常" : getDefectName(bestIdx);

    // 判断是否位置偏移（简单以检测框中心 vs 图像中心）
    float imgCx = origFrame.cols / 2.0f;
    float imgCy = origFrame.rows / 2.0f;
    float boxCx = bestBox.x + bestBox.width  / 2.0f;
    float boxCy = bestBox.y + bestBox.height / 2.0f;
    float offsetRatioX = std::abs(boxCx - imgCx) / imgCx;
    float offsetRatioY = std::abs(boxCy - imgCy) / imgCy;
    bool  positionOk   = (offsetRatioX <= 0.08f) && (offsetRatioY <= 0.08f);

    // ---------- 组装结果 ----------
    DetectionResult result;
    result.grade      = grade;
    result.defect     = defect;
    result.positionOk = positionOk;
    result.resultImage = display;

    // ---------- MQTT 上报 ----------
    QString timestamp = QDateTime::currentDateTime().toString("yyyy-MM-dd hh:mm:ss");
    QString json = QString(
        "{\"timestamp\":\"%1\",\"grade\":%2,\"defect\":\"%3\",\"position_ok\":%4}")
        .arg(timestamp).arg(grade).arg(defect).arg(positionOk ? "true" : "false");

    if (mqttClient && mqttClient->isConnected()) {
        mqttClient->publish("energy_label/result", json);
    }

    emit resultReady(result);
    emit logReady(json);
}
