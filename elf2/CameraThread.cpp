#include "CameraThread.h"

CameraThread::CameraThread(int cameraIndex, QObject *parent)
    : QObject(parent), running(false)
{
    if (cameraIndex == 11) {
        std::string pipeline = 
            "v4l2src device=/dev/video11 ! "
            "video/x-raw,format=NV12,width=640,height=480,framerate=30/1 ! "
            "videoconvert ! "
            "video/x-raw,format=BGR ! "
            "appsink drop=true max-buffers=1 sync=false";
        cap.open(pipeline, cv::CAP_GSTREAMER);
    } else {
        cap.open(cameraIndex, cv::CAP_V4L2);
    }

    if (!cap.isOpened()) return;

    if (cameraIndex != 11) {
        cap.set(cv::CAP_PROP_FOURCC, cv::VideoWriter::fourcc('Y', 'U', 'Y', 'V'));
        cap.set(cv::CAP_PROP_FRAME_WIDTH, 640);
        cap.set(cv::CAP_PROP_FRAME_HEIGHT, 480);
        cap.set(cv::CAP_PROP_FPS, 30);

        // 关闭自动曝光，防止运动拖影（V4L2: 0.25=手动模式）
        cap.set(cv::CAP_PROP_AUTO_EXPOSURE, 0.25);
        // 手动曝光值
        cap.set(cv::CAP_PROP_EXPOSURE, -8);
    }

    // ===== 摄像头标定参数（640x480 分辨率下标定） =====
    // 畸变矫正由摄像头内置光学结构 + 物理支架调平承担
    // 软件畸变矫正已关闭（enableCalib = false）
    bool enableCalib = false;

    if (enableCalib) {
        cameraMatrix = (cv::Mat_<double>(3, 3) <<
            604.6821404315123, 0.0, 291.68003055800085,
            0.0, 605.8782881552803, 193.3665467890653,
            0.0, 0.0, 1.0);

        distCoeffs = (cv::Mat_<double>(1, 5) <<
            -0.46623351002291596, 0.14433911213442974,
            0.00044299408568773663, -0.0007564167797907202, 0.20090674904139205);

        cv::initUndistortRectifyMap(
            cameraMatrix, distCoeffs, cv::Mat(),
            cameraMatrix, cv::Size(640, 480),
            CV_16SC2, map1, map2);
    }
}

void CameraThread::startCapture()
{
    running = true;
    fpsTimer.start();
    frameCount = 0;
    timer = new QTimer(this);

    connect(timer, &QTimer::timeout, this, [this]() {
        if (!running) return;

        cv::Mat origFrame;
        cap >> origFrame;
        if (origFrame.empty()) return;

        // 畸变矫正：仅在 map 存在时执行（当前已关闭）
        cv::Mat undistorted;
        if (!map1.empty() && !map2.empty()) {
            cv::remap(origFrame, undistorted, map1, map2, cv::INTER_LINEAR);
        } else {
            undistorted = origFrame.clone();
        }

        {
            QMutexLocker locker(&mutex);
            currentFrame = undistorted.clone();
        }

        cv::Mat rgbFrame;
        cv::cvtColor(undistorted, rgbFrame, cv::COLOR_BGR2RGB);
        QImage image(rgbFrame.data, rgbFrame.cols, rgbFrame.rows,
                     rgbFrame.step, QImage::Format_RGB888);
        emit frameReady(image.copy());

        frameCount++;
        if (fpsTimer.elapsed() >= 1000) {
            emit fpsUpdated(frameCount);
            frameCount = 0;
            fpsTimer.restart();
        }
    });

    timer->start(33);  // ~30fps
}

cv::Mat CameraThread::getCurrentFrame()
{
    QMutexLocker locker(&mutex);
    return currentFrame.clone();
}

void CameraThread::stop()
{
    running = false;
    if (cap.isOpened()) cap.release();
    // timer 是子线程创建的 QObject，不要从主线程 delete
}
