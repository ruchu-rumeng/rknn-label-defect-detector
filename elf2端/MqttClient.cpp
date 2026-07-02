#include "MqttClient.h"
#include <mosquitto.h>
#include <QDebug>

// mosquitto C 回调（在 loop 线程中调用）
static void on_connect_cb(struct mosquitto *mosq, void *obj, int rc)
{
    (void)mosq;
    MqttClient *client = static_cast<MqttClient*>(obj);
    if (rc == MOSQ_ERR_SUCCESS) {
        client->setConnected(true);
    } else {
        client->setConnected(false);
        emit client->error(QString("connect failed: %1").arg(mosquitto_strerror(rc)));
    }
}

static void on_disconnect_cb(struct mosquitto *mosq, void *obj, int rc)
{
    (void)mosq;
    (void)rc;
    MqttClient *client = static_cast<MqttClient*>(obj);
    client->setConnected(false);
}

MqttClient::MqttClient(QObject *parent) : QObject(parent)
{
    mosquitto_lib_init();
}

MqttClient::~MqttClient()
{
    disconnectBroker();
    mosquitto_lib_cleanup();
}

bool MqttClient::connectBroker(const QString &host, int port, const QString &clientId)
{
    if (mosq) disconnectBroker();

    mosq = mosquitto_new(clientId.toUtf8().constData(), true, this);
    if (!mosq) {
        emit error("mosquitto_new failed");
        return false;
    }

    // 设置回调
    mosquitto_connect_callback_set(mosq, on_connect_cb);
    mosquitto_disconnect_callback_set(mosq, on_disconnect_cb);

    // 异步启动连接（非阻塞，立即返回）
    int ret = mosquitto_connect_async(mosq, host.toUtf8().constData(), port, 60);
    if (ret != MOSQ_ERR_SUCCESS) {
        emit error(QString("connect_async failed: %1").arg(mosquitto_strerror(ret)));
        mosquitto_destroy(mosq);
        mosq = nullptr;
        return false;
    }

    // 启动后台网络线程
    mosquitto_loop_start(mosq);

    return true;  // 只是启动连接流程，不代表已连接成功
}

void MqttClient::disconnectBroker()
{
    if (mosq) {
        m_connected = false;
        mosquitto_loop_stop(mosq, true);
        mosquitto_disconnect(mosq);
        mosquitto_destroy(mosq);
        mosq = nullptr;
        emit disconnected();
    }
}

bool MqttClient::publish(const QString &topic, const QString &payload)
{
    if (!m_connected || !mosq) {
        // 静默跳过，不打断检测流程
        return false;
    }
    int ret = mosquitto_publish(mosq, nullptr,
                                topic.toUtf8().constData(),
                                payload.toUtf8().size(),
                                payload.toUtf8().constData(),
                                1, false);  // QoS=1 确保至少送达一次
    if (ret != MOSQ_ERR_SUCCESS) {
        return false;
    }
    return true;
}

bool MqttClient::isConnected() const
{
    return m_connected;
}

void MqttClient::setConnected(bool connected)
{
    if (m_connected == connected) return;
    m_connected = connected;
    if (connected) {
        emit this->connected();
    } else {
        emit this->disconnected();
    }
}
