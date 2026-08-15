#include "device_config.h"
#include <string.h>
#include "site_config_data.h"

namespace radar {

// Bounds are refused, not clamped. Several of these exist because the value
// below them is silently useless rather than obviously broken:
//
//   poll   500ms   the board would spend its time on HTTP, against a Pi also
//                  running readsb and tar1090
//   mpoll  10s     the METAR proxy caches for 300s, so anything faster just
//                  re-serves the same observation
//   gpoll  60s     the map changes when you publish, not on its own
//
// metaron/geoon are runtime switches for the two optional feeds, so trying the
// panel without weather stops costing a reflash. They cannot turn a feature ON
// that was compiled out — the #ifdef still decides whether the code exists.
//
// coaston/ohon/nighton/nclkon are the same shape but WITHOUT that caveat: the
// code behind them is compiled either way now, and the matching define in
// config.h only chooses the default. Turning one on always works. nclkon is
// subordinate to nighton — nothing goes dark with blanking off, so there is
// nothing for the clock to appear on — and night_mode.cpp ANDs them rather
// than making that a cross-field rule here.
//
// The overhead thresholds are the "is it really overhead?" numbers, and each
// one used to cost a flash to try. ohrnm is in TENTHS of a nautical mile: the
// shipped value is 1.0nm, so whole miles would offer no step below the default
// and the interesting experiments are 0.5 and 2.0. Everything else here is a
// whole number in its natural unit, which is why this is the only field that
// needs its unit spelled out on the page.
//
// sdim/sdrop are seconds of silence before a contact dims and before it is
// dropped. Their floor is 5s rather than 1s because below about two poll
// intervals every contact spends most of its life dimmed, which reads as a
// broken feed. Nothing enforces sdrop > sdim, for the same reason nothing
// enforces the ranges against each other — see below.
//
// amin/amax/mlaton are the only settings the BOARD never acts on. They ride on
// the /contacts request and the Pi filters before it sorts and caps, because
// a real feed runs 54-65 aircraft against 32 slots: a filter behind the cap
// would spend every slot and then hide most of them, leaving the scope
// emptiest exactly when the sky is busy. amin of 0 means no floor at all —
// baro altitude genuinely reads negative at a low airfield under high
// pressure, so a literal floor of 0 would hide ground traffic at the shipped
// setting. amin above amax is refused by neither side and IGNORED by the Pi,
// because obeying it blanks the scope and a blank scope reads as a dead board.
// mlaton off frees those slots for positions the aircraft transmitted itself,
// at the price of the signal the hollow ring carries — not sending ADS-B in
// this airspace is itself worth seeing. Nothing on the board changes: the
// status strip's "(n)" is already conditional on there being any.
//
// nstart == nend is ALLOWED: night_mode.cpp reads it as "disabled", so it is
// the off switch rather than a 24-hour blank.
//
// The ranges are whole nautical miles. 200 is the ceiling on all of them
// because the usable radius is 110px: at 200nm a nautical mile is half a
// pixel, so two aircraft a mile apart draw on the same one and the picture
// stops being a picture. The floors are 5 for the overview — below that it is
// no longer a chooser, it is just a third detail level — and 1 for a detail
// range, where a single blip and its datablock already fill the panel. tlnm
// alone may be 0, meaning no datablock ever gets a second line.
//
// Nothing here can express "the overview must be wider than the detail": each
// field is validated on its own, and the config server writes them one at a
// time, so a cross-field rule would make some orders of the same edit fail.
// Getting it wrong costs a strange-looking scope, not a broken board.
//
// String maxima are CFG_HOST_LEN and CFG_TZ_LEN less the terminator, so a
// value that passes here is one cfgSetStr() will also accept. Deriving them
// from the same constants rather than writing 32 and 47 is what keeps that
// true if a field is ever resized.
const DeviceField DEVICE_FIELDS[] = {
    {"nstart", DEV_U32, 0, 23},
    {"nend", DEV_U32, 0, 23},
    {"nwake", DEV_U32, 5, 3600},
    {"nfade", DEV_U32, 0, 10000},
    {"nduty", DEV_U32, 0, 255},
    {"poll", DEV_U32, 500, 60000},
    {"mpoll", DEV_U32, 10000, 3600000},
    {"gpoll", DEV_U32, 60000, 86400000},
    {"metaron", DEV_U32, 0, 1},
    {"geoon", DEV_U32, 0, 1},
    {"coaston", DEV_U32, 0, 1},
    {"ohon", DEV_U32, 0, 1},
    {"nighton", DEV_U32, 0, 1},
    {"nclkon", DEV_U32, 0, 1},
    {"ovnm", DEV_U32, 5, 200},
    {"d1nm", DEV_U32, 1, 200},
    {"d2nm", DEV_U32, 1, 200},
    {"tlnm", DEV_U32, 0, 200},
    // Tenths of a nautical mile: 2 is 0.2nm, 100 is 10nm, 10 is shipped. The
    // ceiling is the overview's own floor — a miss distance wider than the
    // narrowest view you can select is not a prediction about overhead.
    {"ohrnm", DEV_U32, 2, 100},
    // Below 30s nothing has time to arrive; above 600s the aircraft has more
    // time to change its mind than the straight-line extrapolation has
    // validity, which is the whole reason the threshold exists.
    {"ohsec", DEV_U32, 30, 600},
    // A standard-rate turn is ~43 deg/nm at 250kt, so 45 admits everything and
    // makes the steadiness test a no-op — deliberately reachable, because
    // "does the filter matter?" is a question worth being able to answer.
    {"ohturn", DEV_U32, 1, 45},
    {"sdim", DEV_U32, 5, 3600},
    {"sdrop", DEV_U32, 5, 3600},
    // Whole feet. Bounds derived from the shared ceiling rather than written
    // as 70000, so the Pi's ALT_BAND_CEILING_FT and this cannot drift.
    {"amin", DEV_U32, 0, CFG_ALT_CEILING_FT},
    {"amax", DEV_U32, 0, CFG_ALT_CEILING_FT},
    {"mlaton", DEV_U32, 0, 1},
    {"ntp", DEV_STR, 0, CFG_HOST_LEN - 1},
    {"tz", DEV_STR, 0, CFG_TZ_LEN - 1},
    {"types", DEV_STR, 0, CFG_TYPES_LEN - 1},
};

const size_t DEVICE_FIELD_COUNT =
    sizeof(DEVICE_FIELDS) / sizeof(DEVICE_FIELDS[0]);

const DeviceField *deviceFieldByKey(const char *key) {
  if (!key) return nullptr;
  for (size_t i = 0; i < DEVICE_FIELD_COUNT; i++)
    if (strcmp(DEVICE_FIELDS[i].key, key) == 0) return &DEVICE_FIELDS[i];
  return nullptr;
}

const char *deviceFieldProblem(const DeviceField &field, const char *value,
                               uint32_t *out) {
  if (!value) return "missing";

  if (field.kind == DEV_STR) {
    size_t n = strlen(value);
    if (n == 0) return "empty";
    if (n > field.high) return "too long for this field";
    return nullptr;
  }

  // Hand-parsed rather than strtoul, to reject what strtoul accepts. A
  // leading '-' would wrap to a huge unsigned; trailing text is silently
  // ignored, so "2000ms" would store 2000 and the next reader would wonder
  // where the units went.
  if (value[0] == '\0') return "empty";
  uint64_t n = 0;
  for (const char *p = value; *p; p++) {
    if (*p < '0' || *p > '9') return "expected a whole number";
    n = n * 10 + (uint64_t)(*p - '0');
    if (n > 0xFFFFFFFFull) return "out of range";
  }
  if (n < field.low || n > field.high) return "out of range";
  if (out) *out = (uint32_t)n;
  return nullptr;
}

} // namespace radar
