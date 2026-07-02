#ifndef MQTTCLIENT_H
#define MQTTCLIENT_H

#include <QObject>
#include <QString>

struct mosquitto;

class MqttClient : public QObject
{
    Q_OBJECT

public:
    explicit MqttClient(QObject *parent = nullptr);
    ~MqttClient();

    // 异步启动连接（不阻塞，立即返回）
    bool connectBroker(const QString &host, int port, const QString &clientId);
    void disconnectBroker();

    bool publish(const QString &topic, const QString &payload);
    bool isConnected() const;

    // 供 C 回调使用（内部）
    void setConnected(bool connected);

signals:
    void connected();
    void disconnected();
    void error(const QString &msg);

private:
    mosquitto *mosq = nullptr;
    bool m_connected = false;
};

#endif
