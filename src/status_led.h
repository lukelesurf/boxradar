#pragma once
enum class LedStatus { NoWifi, NoData, Ok };
void statusLedInit();
void statusLedSet(LedStatus s);
