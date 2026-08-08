#pragma once
#include <stdint.h>

// First-run configuration portal: the board raises its own access point and
// serves a form that writes the site config to NVS.
//
// SPEC.md listed "web config portal" as a non-goal, justified as "hardcoded
// config is fine for one unit on one shelf". That premise is exactly what the
// runtime-config work changes, so the non-goal is reopened deliberately.
//
// Two safety properties, and they matter more than the form does:
//
//   1. TIME-BOXED. If nobody configures it within PORTAL_TIMEOUT_MS the portal
//      gives up, tears the AP down and lets the boot continue in STA mode. A
//      spuriously-triggered portal therefore self-heals into a board that is
//      back on the LAN and reachable over OTA, with no intervention. Without
//      this, one bad trigger strands the board behind an AP nobody is looking
//      for.
//   2. IT ANNOUNCES ITSELF ON SCREEN. The RGB LED is invisible with the board
//      in its case and no speaker is fitted, so the panel is the only channel
//      the device has. A portal nobody can discover is the same as no portal.
//
// The portal never runs when WiFi associated successfully, so a working board
// cannot be pushed into it by accident.

// How long to wait for someone to configure it before giving up and carrying
// on. Long enough to fetch a phone, short enough that an accidental trigger is
// an inconvenience rather than a callout.
// Overridable so the exit path can be tested in seconds instead of minutes —
// that path is the safety property, so it needs to be cheap to exercise.
#ifndef PORTAL_TIMEOUT_MS
#define PORTAL_TIMEOUT_MS (5UL * 60UL * 1000UL)
#endif

// AP details. Open rather than WPA2 deliberately: the alternative is baking a
// shared password into published firmware, which protects nothing, and the
// window is minutes long on a LAN you already trust enough to run this on.
#define PORTAL_AP_SSID "boxradar-setup"

// Blocking. Raises the AP, serves the form, and returns when either a config
// was saved (having rebooted, so it does not actually return) or the timeout
// expired. Safe to call with the TFT already initialised; draws its own status.
// Leaves WiFi in STA mode on the way out.
void portalRun();

// True when the portal should run: association failed AND the portal has not
// already been tried this boot. Forced by -DPORTAL_FORCE for testing.
bool portalShouldRun(bool wifiConnected);
