#include "CameraThread.h"
#include <QDebug>
#include <QTimer>

CameraThread::CameraThread(int cameraIndex, QObject *parent)
    : QObject(parent), timer(nullptr), running(false)
{
    cap.open(cameraIndex, cv::CAP_V4L2);
    if (!cap.isOpened()) {
        qDebug() << "无法打开摄像头" << cameraIndex;
        return;
    }

    // 设置 MJPEG 格式、1280x960、30fps
    cap.set(cv::CAP_PROP_FOURCC, cv::VideoWriter::fourcc('M', 'J', 'P', 'G'));
    cap.set(cv::CAP_PROP_FRAME_WIDTH, 1280);
    cap.set(cv::CAP_PROP_FRAME_HEIGHT, 960);
    cap.set(cv::CAP_PROP_FPS, 30);
    cap.set(cv::CAP_PROP_AUTO_EXPOSURE, 0.25);
    cap.set(cv::CAP_PROP_EXPOSURE, -8);

    // 等待并打印实际参数
    cv::Mat testFrame;
    cap.read(testFrame);
    qDebug() << "摄像头" << cameraIndex
             << "实际分辨率:" << cap.get(cv::CAP_PROP_FRAME_WIDTH) << "x" << cap.get(cv::CAP_PROP_FRAME_HEIGHT)
             << "格式:" << cap.get(cv::CAP_PROP_FOURCC)
             << "FPS:" << cap.get(cv::CAP_PROP_FPS);

    // 摄像头标定参数（640x480 分辨率下标定）
    cameraMatrix = (cv::Mat_<double>(3,3) <<
        604.688456, 0.0,        327.102018,
        0.0,        604.593287, 236.481476,
        0.0,        0.0,        1.0);
    distCoeffs = (cv::Mat_<double>(1,5) <<
        -0.328394, 0.097167, 0.000218, -0.000144, 0.0);

    // 预计算畸变矫正映射表（基于 640x480）
    cv::initUndistortRectifyMap(cameraMatrix, distCoeffs, cv::Mat(),
        cameraMatrix, cv::Size(640, 480), CV_16SC2, map1, map2);
}

cv::Mat CameraThread::getCurrentFrame()
{
    QMutexLocker locker(&mutex);
    return currentFrame.clone();
}

void CameraThread::startCapture()
{
    running = true;
    fpsTimer.start();
    frameCount = 0;

    timer = new QTimer(this);
    connect(timer, &QTimer::timeout, this, [this]() {
        cv::Mat frame, resized, undistorted;
        if (!cap.read(frame)) {
            qDebug() << "帧读取失败";
            return;
        }

        // 1. 先缩放到 640x480（标定分辨率）
        cv::resize(frame, resized, cv::Size(640, 480), 0, 0, cv::INTER_LINEAR);

        // 2. 畸变矫正
        cv::remap(resized, undistorted, map1, map2, cv::INTER_LINEAR);

        {
            QMutexLocker locker(&mutex);
            currentFrame = undistorted.clone();
        }

        // 3. 转 QImage 并发送
        QImage image(undistorted.data, undistorted.cols, undistorted.rows,
                     static_cast<int>(undistorted.step), QImage::Format_BGR888);
        emit frameReady(image.copy());

        // FPS 统计
        frameCount++;
        if (fpsTimer.elapsed() >= 1000) {
            emit fpsUpdated(frameCount);
            frameCount = 0;
            fpsTimer.restart();
        }
    });
    timer->start(33);  // ~30fps
}

void CameraThread::stop()
{
    running = false;
    if (timer) {
        timer->stop();
        delete timer;
        timer = nullptr;
    }
    if (cap.isOpened()) {
        cap.release();
    }
}
