QT += core gui widgets

TARGET = hello
TEMPLATE = app

DEFINES += QT_DEPRECATED_WARNINGS

CONFIG += c++11
INCLUDEPATH += /home/elf/qt_ws/hello

SOURCES += \
        main.cpp \
        widget.cpp \
        CameraThread.cpp \
        RKNNModel.cpp \
        InferenceThread.cpp \
        MqttClient.cpp

HEADERS += \
        widget.h \
        CameraThread.h \
        RKNNModel.h \
        InferenceThread.h \
        MqttClient.h

FORMS += \
        widget.ui

# ============ OpenCV ============
CONFIG += link_pkgconfig
PKGCONFIG += opencv4

# ============ RKNPU ============
LIBS += -L/usr/lib -lrknnrt -lmosquitto

# Default rules for deployment.
qnx: target.path = /tmp/$${TARGET}/bin
else: unix:!android: target.path = /opt/$${TARGET}/bin
!isEmpty(target.path): INSTALLS += target
