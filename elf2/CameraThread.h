#ifndef CAMERATHREAD_H
#define CAMERATHREAD_H

#include <QObject>
#include <QTimer>
#include <QElapsedTimer>
#include <QImage>
#include <opencv2/opencv.hpp>

class CameraThread : public QObject
{
    Q_OBJECT

public:
    explicit CameraThread(int cameraIndex = 0, QObject *parent = nullptr);
    void stop();
    cv::Mat getCurrentFrame();

public slots:
    void startCapture();

signals:
    void frameReady(QImage image);
    void fpsUpdated(int fps);

private:
    cv::VideoCapture cap;
    QTimer *timer;
    bool running;
    cv::Mat currentFrame;
    int frameCount = 0;
    QElapsedTimer fpsTimer;

    // 摄像头标定参数（640x480 分辨率下标定）
    cv::Mat cameraMatrix;
    cv::Mat distCoeffs;
    cv::Mat map1, map2;
};

#endif
