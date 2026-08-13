#pragma once
#include <stdint.h>

// A press-and-hold gesture, as a state machine over "how long has the finger
// been down".
//
// Touch on this panel is single-point and edge-triggered — XPT2046 is a 4-wire
// resistive controller, so there is no multi-touch to detect and `z` measures
// contact force rather than finger count. Position is fully spoken for by the
// existing tap gestures (see src/ui/touch_input.h), which leaves DURATION as
// the only unclaimed axis. Holding currently does nothing at all, so a
// long press collides with nothing and needs no affordance drawn at rest.
//
// Pure and Arduino-free so the timing lives in [env:native] tests. The caller
// supplies the elapsed time; this owns only the decision.

namespace radar {

enum HoldState {
  HOLD_IDLE,       // nothing happening
  HOLD_HINTING,    // held long enough to show the countdown
  HOLD_FIRED,      // reached the threshold, exactly once
  HOLD_CANCELLED,  // released after hinting, before firing
};

class HoldGesture {
public:
  HoldGesture(uint32_t hintMs, uint32_t fireMs)
      : m_hintMs(hintMs), m_fireMs(fireMs), m_armed(false), m_fired(false) {}

  // `heldMs` is 0 when nothing is pressed, otherwise how long the current
  // continuous press has lasted. Call once per frame.
  HoldState update(uint32_t heldMs);

  // 0..1 across the window between hint and fire, for drawing the countdown.
  // Below the hint threshold it is 0, so a normal tap never flickers a bar.
  float progress(uint32_t heldMs) const;

private:
  uint32_t m_hintMs;
  uint32_t m_fireMs;
  bool m_armed;   // the countdown has been shown for this press
  bool m_fired;   // latched, so one press cannot fire twice
};

} // namespace radar
