#include "InferenceThread.h"
#include "CameraThread.h"
#include "MqttClient.h"
#include <QDateTime>
#include <algorithm>
#include <QDebug>
// ===== MQTT 配置（部署时修改）=====
#define MQTT_DEVICE_ID    "elf2-line01"    // 设备唯一标识（产线编号）

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
    if (!detector.load(detectorPath.toStdString())) return false;
    if (!classifier.load(classifierPath.toStdString())) return false;
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
    if (!cameraThread) return;
    running = true;
}

void InferenceThread::stop()
{
    running = false;
}

cv::Mat InferenceThread::letterbox(const cv::Mat &src, int targetSize,
                                      float &scale, int &offsetX, int &offsetY,
                                      const cv::Scalar &padColor)
{
    scale = std::min((float)targetSize / src.cols, (float)targetSize / src.rows);
    int newW = cvRound(src.cols * scale);
    int newH = cvRound(src.rows * scale);
    offsetY = (targetSize - newH) / 2;
    offsetX = (targetSize - newW) / 2;

    cv::Mat resized;
    cv::resize(src, resized, cv::Size(newW, newH), 0, 0, cv::INTER_LINEAR);

    cv::Mat dst(targetSize, targetSize, CV_8UC3, padColor);
    resized.copyTo(dst(cv::Rect(offsetX, offsetY, newW, newH)));
    return dst;
}

std::vector<std::pair<cv::Rect, float>> InferenceThread::postProcess(const std::vector<float> &output,
                                                      float scale, int padTop, int padLeft,
                                                      int origW, int origH)
{
    const int numAnchors = 8400;
    const float confThreshold = 0.25f;   // 交接文件要求：conf >= 0.25   
    const float minBoxArea = 35.0f;      // 面积过滤

    struct Box { float x1, y1, x2, y2, conf; };
    std::vector<Box> candidates;

    for (int i = 0; i < numAnchors; i++) {
        float cx   = output[0 * numAnchors + i];
        float cy   = output[1 * numAnchors + i];
        float w    = output[2 * numAnchors + i];
        float h    = output[3 * numAnchors + i];
        float conf = sigmoid(output[4 * numAnchors + i]);

        if (conf < confThreshold) continue;

        float x1 = cx - w * 0.5f;
        float y1 = cy - h * 0.5f;
        float x2 = cx + w * 0.5f;
        float y2 = cy + h * 0.5f;

        x1 = std::max(0.0f, std::min(x1, 639.0f));
        y1 = std::max(0.0f, std::min(y1, 639.0f));
        x2 = std::max(0.0f, std::min(x2, 639.0f));
        y2 = std::max(0.0f, std::min(y2, 639.0f));

        if (x2 <= x1 || y2 <= y1) continue;

        float boxArea = (x2 - x1) * (y2 - y1);
        if (boxArea < minBoxArea) continue;

        candidates.push_back({x1, y1, x2, y2, conf});
    }

    if (candidates.empty()) return std::vector<std::pair<cv::Rect, float>>();

    std::sort(candidates.begin(), candidates.end(),
              [](const Box& a, const Box& b) { return a.conf > b.conf; });

    if (candidates.size() > 60) candidates.resize(60);

    std::vector<Box> finalBoxes;
    std::vector<bool> suppressed(candidates.size(), false);

    for (size_t m = 0; m < candidates.size(); m++) {
        if (suppressed[m]) continue;
        finalBoxes.push_back(candidates[m]);

        for (size_t n = m + 1; n < candidates.size(); n++) {
            if (suppressed[n]) continue;

            float ix1 = std::max(candidates[m].x1, candidates[n].x1);
            float iy1 = std::max(candidates[m].y1, candidates[n].y1);
            float ix2 = std::min(candidates[m].x2, candidates[n].x2);
            float iy2 = std::min(candidates[m].y2, candidates[n].y2);

            if (ix2 <= ix1 || iy2 <= iy1) continue;

            float inter = (ix2 - ix1) * (iy2 - iy1);
            float areaA = (candidates[m].x2 - candidates[m].x1) * (candidates[m].y2 - candidates[m].y1);
            float areaB = (candidates[n].x2 - candidates[n].x1) * (candidates[n].y2 - candidates[n].y1);
            float iou = inter / (areaA + areaB - inter + 1e-6f);

            if (iou > 0.5f) suppressed[n] = true;
        }
    }

    std::vector<std::pair<cv::Rect, float>> result;
    for (auto& b : finalBoxes) {
        float x1 = (b.x1 - padLeft) / scale;
        float y1 = (b.y1 - padTop) / scale;
        float x2 = (b.x2 - padLeft) / scale;
        float y2 = (b.y2 - padTop) / scale;

        x1 = std::max(0.0f, x1); y1 = std::max(0.0f, y1);
        x2 = std::min((float)origW, x2); y2 = std::min((float)origH, y2);

        if (x2 > x1 && y2 > y1) {
            result.emplace_back(cv::Rect(cv::Point(x1, y1), cv::Point(x2, y2)), b.conf);
        }
    }
    return result;
}

QString InferenceThread::getDefectName(int idx)
{
    const char* names[] = {"normal", "damage", "stain", "wrinkle"};
    if (idx >= 0 && idx < 4) return QString(names[idx]);
    return "unknown";
}

/* ========== 蓝色标签矫正：minAreaRect + warpAffine 旋转扶正 ========== */
cv::Mat InferenceThread::correctLabel(const cv::Mat& roi)
{
    if (roi.empty()) return roi;

    // 1. 转换到 HSV，提取蓝色区域
    cv::Mat hsv;
    cv::cvtColor(roi, hsv, cv::COLOR_RGB2HSV);

    cv::Mat mask;
    cv::inRange(hsv, cv::Scalar(100, 60, 60), cv::Scalar(140, 255, 255), mask);

    // 2. 形态学操作去噪 + 闭运算连接断裂区域
    cv::Mat kernel = cv::getStructuringElement(cv::MORPH_RECT, cv::Size(5, 5));
    cv::morphologyEx(mask, mask, cv::MORPH_CLOSE, kernel);
    cv::morphologyEx(mask, mask, cv::MORPH_OPEN,  kernel);

    // 3. 找轮廓
    std::vector<std::vector<cv::Point>> contours;
    cv::findContours(mask, contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE);
    if (contours.empty()) {
        qDebug() << "[correctLabel] no blue region found, skip correction";
        return roi;
    }

    // 4. 取最大轮廓（应为蓝色标签主体）
    double maxArea = 0;
    int maxIdx = -1;
    for (int i = 0; i < (int)contours.size(); ++i) {
        double area = cv::contourArea(contours[i]);
        if (area > maxArea) {
            maxArea = area;
            maxIdx = i;
        }
    }
    if (maxIdx < 0 || maxArea < roi.total() * 0.05) {
        qDebug() << "[correctLabel] blue region too small, skip correction";
        return roi;
    }

    // 5. minAreaRect 获取最小外接矩形
    cv::RotatedRect minRect = cv::minAreaRect(contours[maxIdx]);

    // 6. 计算旋转角度（OpenCV minAreaRect 返回 angle ∈ [-90, 0)）
    float angle = minRect.angle;
    if (minRect.size.width < minRect.size.height) {
        angle = 90 + angle;   // 让长边（height）竖直
    } else {
        angle = -angle;       // 让长边（width）水平，取反使图像转正
    }

    // 角度很小，无需矫正
    if (std::abs(angle) < 2.0f) {
        return roi;
    }

    // 7. 计算旋转后完整边界，避免裁剪
    cv::Point2f center(roi.cols / 2.0f, roi.rows / 2.0f);
    cv::Mat rotMat = cv::getRotationMatrix2D(center, angle, 1.0);

    double cosA = std::abs(rotMat.at<double>(0, 0));
    double sinA = std::abs(rotMat.at<double>(0, 1));
    int newW = int(roi.rows * sinA + roi.cols * cosA);
    int newH = int(roi.rows * cosA + roi.cols * sinA);
    rotMat.at<double>(0, 2) += (newW - roi.cols) / 2.0;
    rotMat.at<double>(1, 2) += (newH - roi.rows) / 2.0;

    cv::Mat rotated;
    cv::warpAffine(roi, rotated, rotMat, cv::Size(newW, newH),
                   cv::INTER_LINEAR, cv::BORDER_CONSTANT, cv::Scalar(0, 0, 0));

    return rotated;
}

void InferenceThread::doInference()
{
    if (!running || !cameraThread) return;

    cv::Mat origFrame = cameraThread->getCurrentFrame();
    if (origFrame.empty()) return;

    cv::Mat rgbFrame;
    cv::cvtColor(origFrame, rgbFrame, cv::COLOR_BGR2RGB);

    float scale;
    int offsetX, offsetY;
    cv::Mat detInput = letterbox(rgbFrame, 640, scale, offsetX, offsetY, cv::Scalar(114, 114, 114));

    if (!detector.inference(detInput)) return;

    auto detOutput = detector.getOutputBuffer();
    auto boxes = postProcess(detOutput, scale, offsetY, offsetX, origFrame.cols, origFrame.rows);
    if (boxes.empty()) {
        cv::Mat resultImg = origFrame.clone();
        cv::putText(resultImg, "No target", cv::Point(50, 50),
                    cv::FONT_HERSHEY_SIMPLEX, 1.0, cv::Scalar(0, 0, 255), 2);
        DetectionResult result;
        result.grade = 0;
        result.defect = "none";
        result.positionOk = false;
        result.resultImage = resultImg;
        emit resultReady(result);
        return;
    }

    cv::Rect bestBox = boxes[0].first;
    float bestConf = boxes[0].second;

    // ========== Classifier 预处理（按交接文件）==========
    // 1. 根据 detector 输出 bbox，从原图中裁出 label 区域
    cv::Mat roi;
    {
        int x1 = std::max(0, bestBox.x);
        int y1 = std::max(0, bestBox.y);
        int x2 = std::min(origFrame.cols, bestBox.x + bestBox.width);
        int y2 = std::min(origFrame.rows, bestBox.y + bestBox.height);
        if (x2 > x1 && y2 > y1) {
            roi = rgbFrame(cv::Rect(x1, y1, x2 - x1, y2 - y1)).clone();
        }
    }

    if (roi.empty()) {
        qDebug() << "[CLS] ROI empty after crop";
        return;
    }

    // 2. 根据蓝色标签区域做矫正
    cv::Mat corrected = correctLabel(roi);

    // 3. Letterbox 到 320 x 320（保持比例 + 灰边填充，避免拉伸）
    float clsScale;
    int clsOffsetX, clsOffsetY;
    cv::Mat clsInput = letterbox(corrected, 320, clsScale, clsOffsetX, clsOffsetY, cv::Scalar(128, 128, 128));

    // 4. 图像增强：降噪 + 锐化
    cv::Mat denoised;
    cv::medianBlur(clsInput, denoised, 3);
    cv::Mat blurred;
    cv::GaussianBlur(denoised, blurred, cv::Size(0, 0), 3.0);
    cv::addWeighted(denoised, 2.0, blurred, -1.0, 0, clsInput);

    // ===== 调试代码已注释（开发时取消注释即可保存中间结果）=====
    /*
    static int clsDebugCount = 0;
    QString debugPath = QString("/home/elf/qt_ws/hello/debug_cls_input_%1.png")
                        .arg(++clsDebugCount % 100);
    cv::Mat bgrForSave;
    cv::cvtColor(clsInput, bgrForSave, cv::COLOR_RGB2BGR);
    cv::imwrite(debugPath.toStdString(), bgrForSave);
    qDebug() << "[DEBUG] saved classifier input:" << debugPath;
    */

    if (!classifier.inference(clsInput)) return;

    int grade = 1;
    int defectIdx = 0;
    auto clsOutput = classifier.getOutputBuffer();
    
    if (clsOutput.size() < 9) {
        qDebug() << "[CLS] ERROR: expected 9 outputs, got" << clsOutput.size();
        return;
    }
    
    // 完整模型：5 grade + 4 defect
    float maxGrade = clsOutput[0];
    for (int i = 1; i < 5; i++) {
        if (clsOutput[i] > maxGrade) { maxGrade = clsOutput[i]; grade = i + 1; }
    }
    float maxDefect = clsOutput[5];
    for (int i = 1; i < 4; i++) {
        if (clsOutput[5 + i] > maxDefect) { maxDefect = clsOutput[5 + i]; defectIdx = i; }
    }

    cv::Mat resultImg = origFrame.clone();
    cv::rectangle(resultImg, bestBox, cv::Scalar(0, 255, 0), 2);

    QString label = QString("Grade:%1 Defect:%2").arg(grade).arg(getDefectName(defectIdx));
    int baseline = 0;
    cv::Size textSize = cv::getTextSize(label.toStdString(), cv::FONT_HERSHEY_SIMPLEX, 0.7, 2, &baseline);
    cv::Point textOrg(bestBox.x, bestBox.y - 5);
    if (textOrg.y < textSize.height) textOrg.y = bestBox.y + bestBox.height + textSize.height + 5;
    cv::putText(resultImg, label.toStdString(), textOrg,
                cv::FONT_HERSHEY_SIMPLEX, 0.7, cv::Scalar(0, 255, 0), 2);

    QString confLabel = QString("conf:%1").arg(bestConf, 0, 'f', 3);
    cv::Size confTextSize = cv::getTextSize(confLabel.toStdString(), cv::FONT_HERSHEY_SIMPLEX, 0.6, 2, &baseline);
    cv::Point confOrg(bestBox.x + bestBox.width - confTextSize.width, bestBox.y - 5);
    if (confOrg.y < confTextSize.height) confOrg.y = bestBox.y + bestBox.height + confTextSize.height + 5;
    cv::putText(resultImg, confLabel.toStdString(), confOrg,
                cv::FONT_HERSHEY_SIMPLEX, 0.6, cv::Scalar(0, 255, 255), 2);

    float imgCenterX = origFrame.cols / 2.0f;
    float imgCenterY = origFrame.rows / 2.0f;
    float boxCenterX = bestBox.x + bestBox.width / 2.0f;
    float boxCenterY = bestBox.y + bestBox.height / 2.0f;
    float offsetRatioX = (boxCenterX - imgCenterX) / origFrame.cols;
    float offsetRatioY = (boxCenterY - imgCenterY) / origFrame.rows;
    bool positionOk = (std::abs(offsetRatioX) <= 0.15f) && (std::abs(offsetRatioY) <= 0.15f);

    DetectionResult result;
    result.grade = grade;
    result.defect = getDefectName(defectIdx);
    result.positionOk = positionOk;
    result.resultImage = resultImg;

    emit resultReady(result);

    static int s_id = 0;
    QString timeStr = QDateTime::currentDateTime().toString("yyyy-MM-dd HH:mm:ss");
    QString deviceId = QStringLiteral(MQTT_DEVICE_ID);

    QString json = QString(
        "{"
        "\"device_id\":\"%1\","
        "\"timestamp\":\"%2\","
        "\"seq_id\":%3,"
        "\"grade\":%4,"
        "\"defect\":\"%5\","
        "\"position_ok\":%6"
        "}"
    )
    .arg(deviceId)
    .arg(timeStr)
    .arg(++s_id)
    .arg(grade)
    .arg(getDefectName(defectIdx))
    .arg(positionOk ? "true" : "false");
    emit logReady(json);

    // ===== MQTT 上报检测结果 =====
    if (mqttClient) {
        QString topic = QString("elf2/%1/detect/result").arg(deviceId);
        mqttClient->publish(topic, json);
    }
}
