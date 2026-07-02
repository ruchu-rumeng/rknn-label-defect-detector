#ifndef RKNNMODEL_H
#define RKNNMODEL_H

#include <opencv2/opencv.hpp>
#include <string>
#include <vector>
#include "rknn_api.h"

class RKNNModel {
public:
    RKNNModel();
    ~RKNNModel();

    bool load(const std::string& modelPath);
    bool inference(const cv::Mat& inputImage);
    std::vector<float> getOutput(int outputIndex = 0);
    const std::vector<float>& getOutputBuffer() const;  // 引用返回，避免拷贝

    int getInputH() const;
    int getInputW() const;
    int getInputC() const;

private:
    void release();

    rknn_context ctx;                 // NPU 句柄
    bool isLoaded;                    // 是否加载成功

    int inputH, inputW, inputC;       // 模型输入尺寸
    size_t outputSize;                // 输出元素个数
    std::vector<float> outputBuf;
    std::vector<rknn_tensor_attr> outputAttrs;
    std::vector<uint8_t> modelData;     // ← 加上这个
};

#endif
