#include "shared_state.h"
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

volatile bool g_otaActive = false;
volatile uint8_t g_otaProgress = 0;

static SemaphoreHandle_t s_mutex;
static radar::AircraftStore s_store;

void sharedStateInit() {
  s_mutex = xSemaphoreCreateMutex();
  s_store.clear();
}

void publishStore(const radar::AircraftStore &s) {
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  s_store = s;
  xSemaphoreGive(s_mutex);
}

void snapshotStore(radar::AircraftStore &out) {
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  out = s_store;
  xSemaphoreGive(s_mutex);
}
