#include "site_config_data.h"
#include <string.h>

namespace radar {

bool cfgSetStr(char *dst, size_t cap, const char *src) {
  if (!dst || cap == 0) return false;
  if (!src) {
    dst[0] = '\0';
    return true;
  }
  size_t n = strlen(src);
  if (n >= cap) return false;  // refuse, never truncate
  memcpy(dst, src, n + 1);
  return true;
}

const char *siteConfigProblem(const SiteConfig &cfg) {
  if (cfg.wifiSsid[0] == '\0') return "no WiFi SSID";
  if (cfg.receiverUrl[0] == '\0') return "no receiver URL";
  // A home position of exactly 0,0 is in the Gulf of Guinea. It is far more
  // likely to mean "never set" than to be a real site, and the whole map
  // would silently project around the wrong place.
  if (cfg.homeLat == 0.0f && cfg.homeLon == 0.0f) return "home is 0,0 (unset?)";
  if (cfg.homeLat < -90.0f || cfg.homeLat > 90.0f) return "home latitude out of range";
  if (cfg.homeLon < -180.0f || cfg.homeLon > 180.0f) return "home longitude out of range";
  if (cfg.pollIntervalMs < 250) return "aircraft poll interval under 250ms";
  if (cfg.nightStartHour > 23 || cfg.nightEndHour > 23) return "night hour out of range";
  return "";
}

bool siteConfigValid(const SiteConfig &cfg) {
  return siteConfigProblem(cfg)[0] == '\0';
}

} // namespace radar
