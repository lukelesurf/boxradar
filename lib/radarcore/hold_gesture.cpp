#include "hold_gesture.h"

namespace radar {

HoldState HoldGesture::update(uint32_t heldMs) {
  if (heldMs == 0) {
    // Released. A press that showed the countdown and let go before the end
    // is a CANCEL and the caller has to undo whatever the press edge did —
    // the first touch of a long press still fires its normal tap action,
    // because touch is edge-triggered and the hold cannot be known yet.
    bool cancelled = m_armed && !m_fired;
    m_armed = false;
    m_fired = false;
    return cancelled ? HOLD_CANCELLED : HOLD_IDLE;
  }

  if (heldMs >= m_fireMs) {
    // Latched: without this, every frame past the threshold would fire again.
    // The board restarts on the first one, so this matters mostly for keeping
    // the state machine honest under test.
    if (m_fired) return HOLD_IDLE;
    m_fired = true;
    return HOLD_FIRED;
  }

  if (heldMs >= m_hintMs) {
    m_armed = true;
    return HOLD_HINTING;
  }

  // Still inside the ordinary tap window. Nothing is drawn, so a tap never
  // flashes a countdown at you.
  return HOLD_IDLE;
}

float HoldGesture::progress(uint32_t heldMs) const {
  if (heldMs <= m_hintMs || m_fireMs <= m_hintMs) return 0.0f;
  if (heldMs >= m_fireMs) return 1.0f;
  return (float)(heldMs - m_hintMs) / (float)(m_fireMs - m_hintMs);
}

} // namespace radar
