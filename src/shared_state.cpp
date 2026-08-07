#include "shared_state.h"
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

volatile bool g_otaActive = false;
volatile uint8_t g_otaProgress = 0;
volatile float g_trailSpacingNm = radar::TRAIL_SPACING_DEFAULT_NM;

static SemaphoreHandle_t s_mutex;
static radar::AircraftStore s_store;
static radar::Metar s_metar;

void sharedStateInit() {
  s_mutex = xSemaphoreCreateMutex();
  s_store.clear();
  s_metar = radar::Metar{}; // valid=false until the first successful fetch
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

void publishMetar(const radar::Metar &m) {
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  s_metar = m;
  xSemaphoreGive(s_mutex);
}

void snapshotMetar(radar::Metar &out) {
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  out = s_metar;
  xSemaphoreGive(s_mutex);
}
