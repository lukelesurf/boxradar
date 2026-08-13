#pragma once
#include <stddef.h>
#include <stdint.h>

// The settings the Pi's configuration UI may change, and the rules for each.
//
// These are the ten keys that previously needed an edit to include/config.h
// and a reflash: the night-blanking block, the three poll intervals, and the
// clock. The board's own captive portal covers WiFi, the receiver URL and
// home position; it deliberately does NOT cover these, and it only appears
// when association fails, so in practice they were unreachable.
//
// **WiFi, OTA and receiver keys are absent on purpose.** A typo pushed into
// `otapass` costs OTA access and needs a USB cable to recover; a typo into
// `ssid` costs the board the network that makes it reflashable at all. Those
// stay behind the physical act of joining the setup AP.
//
// Portable on purpose — stdint and string.h only, no Arduino — so it links in
// [env:native] and the ranges are tested off-device. src/config_server.cpp is
// the Arduino half and holds nothing but HTTP.
//
// The Pi mirrors this table in tools/boxradar-site/boxradar_config/device.py,
// and tests/test_config_device_contract.py fails if the two drift. A key or a
// bound that disagrees is not a compile error on either side — it is a setting
// that silently never applies, which is the worst kind of bug this project has
// already paid for once with NVS key types.

namespace radar {

enum DeviceFieldKind {
  DEV_U32,
  DEV_STR,
};

struct DeviceField {
  const char *key;       // the NVS key; <= 15 chars, treated as a wire format
  DeviceFieldKind kind;
  uint32_t low;          // DEV_U32: inclusive minimum
  uint32_t high;         // DEV_U32: inclusive maximum. DEV_STR: max length.
};

extern const DeviceField DEVICE_FIELDS[];
extern const size_t DEVICE_FIELD_COUNT;

// The field with this key, or nullptr. A key that is not here must never
// reach NVS: the board is on an unauthenticated LAN and the Pi is not
// privileged, so "the UI would not send that" is not a guarantee.
const DeviceField *deviceFieldByKey(const char *key);

// Validates `value` against `field`.
//
// Returns nullptr when acceptable, otherwise a short static message. On
// success, DEV_U32 fields write the parsed number to `out`.
//
// Refuses rather than clamps, for the same reason cfgSetStr() refuses rather
// than truncating: a value that did not stick must not look saved.
const char *deviceFieldProblem(const DeviceField &field, const char *value,
                               uint32_t *out);

} // namespace radar
