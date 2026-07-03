#include "RKNNModel.h"
#include <QDebug>
#include <cstdio>
RKNNModel::RKNNModel()
    : ctx(0), isLoaded(false), inputH(0), inputW(0), inputC(0), outputSize(0)
{
}

RKNNModel::~RKNNModel()
{
    release();
}

void RKNNModel::release()
{
    if (ctx) {
        rknn_destroy(ctx);
        ctx = 0;
    }
    isLoaded = false;
    modelData.clear();
    outputBuf.clear();
    outputAttrs.clear();
}

bool RKNNModel::load(const std::string& modelPath)
{
    release();

    FILE* fp = fopen(modelPath.c_str(), "rb");
    if (!fp) {
        qDebug() << "无法打开模型文件:" << QString::fromStdString(modelPath);
        return false;
    }

    fseek(fp, 0, SEEK_END);
    size_t size = ftell(fp);
    fseek(fp, 0, SEEK_SET);

    modelData.resize(size);
    size_t readSize = fread(modelData.data(), 1, size, fp);
    fclose(fp);

    if (readSize != size) {
        qDebug() << "模型文件读取不完整";
        return false;
    }

    int ret = rknn_init(&ctx, modelData.data(), size, 0, nullptr);
    if (ret != 0) {
        qDebug() << "rknn_init 失败，错误码:" << ret;
        ctx = 0;
        return false;
    }

    // 查询输入/输出数量
    rknn_input_output_num ioNum;
    ret = rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &ioNum, sizeof(ioNum));
    if (ret != 0) {
        qDebug() << "查询输入输出数量失败:" << ret;
        release();
        return false;
    }

    // 查询输入尺寸
    if (ioNum.n_input > 0) {
        rknn_tensor_attr inputAttr;
        inputAttr.index = 0;
        ret = rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &inputAttr, sizeof(inputAttr));
        if (ret == 0) {
            inputH = inputAttr.dims[1];
            inputW = inputAttr.dims[2];
            inputC = inputAttr.dims[3];
        }
    }

    // 查询所有输出尺寸（支持双头/多输出模型）
    outputAttrs.resize(ioNum.n_output);
    outputSize = 0;
    for (uint32_t i = 0; i < ioNum.n_output; i++) {
        outputAttrs[i].index = i;
        ret = rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &outputAttrs[i], sizeof(outputAttrs[i]));
        if (ret == 0) {
            size_t sz = 1;
            for (uint32_t j = 0; j < outputAttrs[i].n_dims; j++) {
                sz *= outputAttrs[i].dims[j];
            }
            outputSize += sz;
        }
    }

    outputBuf.resize(outputSize);
    isLoaded = true;
    return true;
}

bool RKNNModel::inference(const cv::Mat& inputImage)
{
    if (!isLoaded || !ctx) {
        qDebug() << "模型未加载";
        return false;
    }

    if (inputImage.rows != inputH || inputImage.cols != inputW || inputImage.channels() != inputC) {
        qDebug() << "输入尺寸不匹配，期望:" << inputH << "x" << inputW << "x" << inputC
                 << "实际:" << inputImage.rows << "x" << inputImage.cols << "x" << inputImage.channels();
        return false;
    }

    rknn_input inputs[1];
    inputs[0].index = 0;
    inputs[0].buf = (void*)inputImage.data;
    inputs[0].size = inputImage.total() * inputImage.elemSize();
    inputs[0].pass_through = 0;
    inputs[0].type = RKNN_TENSOR_UINT8;
    inputs[0].fmt = RKNN_TENSOR_NHWC;

    int ret = rknn_inputs_set(ctx, 1, inputs);
    if (ret != 0) {
        qDebug() << "rknn_inputs_set 失败:" << ret;
        return false;
    }

    ret = rknn_run(ctx, nullptr);
    if (ret != 0) {
        qDebug() << "rknn_run 失败:" << ret;
        return false;
    }

    uint32_t numOutput = outputAttrs.size();
    if (numOutput == 1) {
        // 单输出：预分配（兼容旧模型）
        rknn_output outputs[1];
        outputs[0].index = 0;
        outputs[0].want_float = 1;
        outputs[0].buf = outputBuf.data();
        outputs[0].size = outputBuf.size() * sizeof(float);
        outputs[0].is_prealloc = 1;

        ret = rknn_outputs_get(ctx, 1, outputs, nullptr);
        if (ret != 0) {
            qDebug() << "rknn_outputs_get 失败:" << ret;
            return false;
        }
        rknn_outputs_release(ctx, 1, outputs);
    } else {
        // 多输出：驱动分配，拼接到一个 buffer（支持双头模型）
        std::vector<rknn_output> outputs(numOutput);
        for (uint32_t i = 0; i < numOutput; i++) {
            outputs[i].index = i;
            outputs[i].want_float = 1;
            outputs[i].buf = nullptr;
            outputs[i].size = 0;
            outputs[i].is_prealloc = 0;
        }

        ret = rknn_outputs_get(ctx, numOutput, outputs.data(), nullptr);
        if (ret != 0) {
            qDebug() << "rknn_outputs_get 失败:" << ret;
            return false;
        }

        size_t offset = 0;
        for (uint32_t i = 0; i < numOutput; i++) {
            size_t floatCount = outputs[i].size / sizeof(float);
            float* src = static_cast<float*>(outputs[i].buf);
            memcpy(outputBuf.data() + offset, src, floatCount * sizeof(float));
            offset += floatCount;
        }
        rknn_outputs_release(ctx, numOutput, outputs.data());
    }

    return true;
}

std::vector<float> RKNNModel::getOutput(int outputIndex)
{
    (void)outputIndex;
    if (!isLoaded || outputBuf.empty()) {
        return std::vector<float>();
    }
    return outputBuf;  // 拷贝返回（兼容旧接口）
}

const std::vector<float>& RKNNModel::getOutputBuffer() const
{
    return outputBuf;  // 引用返回，零拷贝
}

int RKNNModel::getInputH() const { return inputH; }
int RKNNModel::getInputW() const { return inputW; }
int RKNNModel::getInputC() const { return inputC; }
