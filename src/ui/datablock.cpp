#include "datablock.h"
#include "palette.h"
#include "format.h"
#include "classify.h"
#include <Arduino.h>
#include <stdio.h>
#include <string.h>

// Occupancy grid. 8px cells over the 320x240 panel = 1200 cells, held as a
// bitfield in 150 bytes of .bss — no allocation, no per-frame clear cost
// worth measuring. This is what stops 30 aircraft in the Stansted arrival
// stream from stacking their blocks into an unreadable smear.
static constexpr int CELL = 8;
static constexpr int GRID_W = SCOPE_W / CELL; // 40
static constexpr int GRID_H = SCOPE_H / CELL; // 30
static uint8_t s_grid[(GRID_W * GRID_H + 7) / 8];

// Font 1 is a 5x7 glyph on a 6px advance, 8px line pitch.
static constexpr int CH_W = 6, CH_H = 8;
static constexpr int LINE_GAP = 2;
static constexpr int ARROW_W = 6;   // climb/descent triangle plus its spacing
static constexpr int VS_THRESHOLD_FPM = 300; // below this, level flight

// Eight candidate slots: the four diagonals close in, then the same four
// pushed further out on a longer leader. The second ring matters more than it
// looks — with only four slots a block in a busy stream runs out of options
// and vanishes, and a label that blinks in and out is worse than one sitting
// slightly further from its blip.
static constexpr int N_SLOTS = 8;
static constexpr int LEAD_NEAR = 6, LEAD_FAR = 16, DROP_FAR = 10;

// Where each aircraft's block went last frame. Without this the placer
// recomputes a fresh global layout every frame, and one blip crossing a cell
// boundary cascades into every other block moving — which reads as the whole
// screen twitching. Keyed by ICAO hex so it survives the store re-sorting by
// range between polls.
struct Placement {
  uint32_t hex;   // 0 = empty slot
  uint8_t slot;   // last winning candidate index
  uint32_t stamp; // frame counter, for evicting aircraft that have gone
};
static constexpr int PLACE_CAP = radar::MAX_AIRCRAFT + 16;
static Placement s_place[PLACE_CAP];
static uint32_t s_frame = 0;
static constexpr uint8_t NO_SLOT = 0xFF;

static inline bool cellSet(int cx, int cy) {
  int i = cy * GRID_W + cx;
  return s_grid[i >> 3] & (1 << (i & 7));
}

static inline void setCell(int cx, int cy) {
  int i = cy * GRID_W + cx;
  s_grid[i >> 3] |= (uint8_t)(1 << (i & 7));
}

void datablocksBegin() {
  memset(s_grid, 0, sizeof(s_grid));
  s_frame++;
}

// Half-open cell range covering a pixel rect, clamped to the grid.
static void cellRange(int x, int y, int w, int h, int &cx0, int &cy0, int &cx1,
                      int &cy1) {
  cx0 = x / CELL;
  cy0 = y / CELL;
  cx1 = (x + w - 1) / CELL;
  cy1 = (y + h - 1) / CELL;
  if (cx0 < 0) cx0 = 0;
  if (cy0 < 0) cy0 = 0;
  if (cx1 >= GRID_W) cx1 = GRID_W - 1;
  if (cy1 >= GRID_H) cy1 = GRID_H - 1;
}

void datablockReserve(int x, int y, int w, int h) {
  int cx0, cy0, cx1, cy1;
  cellRange(x, y, w, h, cx0, cy0, cx1, cy1);
  for (int cy = cy0; cy <= cy1; cy++)
    for (int cx = cx0; cx <= cx1; cx++) setCell(cx, cy);
}

// Fully on-screen AND every covered cell free. Rejecting off-screen rects
// here is what keeps blocks from being half-clipped at the panel edge.
static bool fits(int x, int y, int w, int h) {
  if (x < 0 || y < 0 || x + w > SCOPE_W || y + h > SCOPE_H) return false;
  int cx0, cy0, cx1, cy1;
  cellRange(x, y, w, h, cx0, cy0, cx1, cy1);
  for (int cy = cy0; cy <= cy1; cy++)
    for (int cx = cx0; cx <= cx1; cx++)
      if (cellSet(cx, cy)) return false;
  return true;
}

static Placement *placementFor(uint32_t hex) {
  Placement *freeSlot = nullptr, *oldest = &s_place[0];
  for (auto &p : s_place) {
    if (p.hex == hex) return &p;
    if (!p.hex && !freeSlot) freeSlot = &p;
    if (p.stamp < oldest->stamp) oldest = &p;
  }
  Placement *slot = freeSlot ? freeSlot : oldest; // evict least recently seen
  slot->hex = hex;
  slot->slot = NO_SLOT;
  return slot;
}

static void slotRect(int slot, int sx, int sy, int w, int h, int &x, int &y) {
  int q = slot & 3;
  bool right = q < 2, up = (q % 2) == 0;
  int lead = slot < 4 ? LEAD_NEAR : LEAD_FAR;
  int drop = slot < 4 ? 0 : DROP_FAR;
  x = right ? sx + lead : sx - w - lead;
  y = up ? sy - h - 2 - drop : sy + 3 + drop;
}

static int textW(const char *s) { return (int)strlen(s) * CH_W; }

// Drawn rather than typed: the climb/descent arrow has no dependable glyph in
// font 1, and a 4px triangle reads better at this size than "^" would.
static void drawArrow(TFT_eSprite &spr, int x, int y, bool up, uint16_t col) {
  if (up)
    spr.fillTriangle(x + 2, y + 1, x, y + 6, x + 4, y + 6, col);
  else
    spr.fillTriangle(x + 2, y + 6, x, y + 1, x + 4, y + 1, col);
}

bool drawDatablock(TFT_eSprite &spr, const radar::Aircraft &a, bool dim,
                   bool twoLine) {
  char cs[10];
  radar::formatCallsign(cs, sizeof(cs), a.callsign, a.hex);
  char alt[8];
  radar::formatAltitude(alt, sizeof(alt), a.altFt, a.onGround);

  bool climbing = a.vertRateFpm > VS_THRESHOLD_FPM;
  bool descending = a.vertRateFpm < -VS_THRESHOLD_FPM;
  bool hasArrow = climbing || descending;
  const char *type = a.type[0] ? a.type : "";

  int line2W = textW(alt) + (hasArrow ? ARROW_W : 0) +
               (type[0] ? CH_W / 2 + textW(type) : 0);
  int wide = textW(cs) > line2W ? textW(cs) : line2W;
  int narrow = textW(cs);

  Placement *mem = placementFor(a.hex);
  mem->stamp = s_frame;

  // Order of preference. The remembered slot goes first at both line counts,
  // so a block only moves when its previous home is genuinely taken — and it
  // recovers its second line as soon as the space frees up again.
  int tryLines[N_SLOTS * 2 + 2];
  int trySlot[N_SLOTS * 2 + 2];
  int n = 0;
  if (mem->slot != NO_SLOT) {
    if (twoLine) { tryLines[n] = 2; trySlot[n++] = mem->slot; }
    tryLines[n] = 1; trySlot[n++] = mem->slot;
  }
  if (twoLine)
    for (int c = 0; c < N_SLOTS; c++) {
      if (c == mem->slot) continue;
      tryLines[n] = 2;
      trySlot[n++] = c;
    }
  for (int c = 0; c < N_SLOTS; c++) {
    if (c == mem->slot) continue;
    tryLines[n] = 1;
    trySlot[n++] = c;
  }

  for (int i = 0; i < n; i++) {
    bool two = tryLines[i] == 2;
    int w = two ? wide : narrow;
    int h = two ? CH_H + LINE_GAP + CH_H : CH_H;
    int bx, by;
    slotRect(trySlot[i], a.sx, a.sy, w, h, bx, by);
    if (!fits(bx, by, w, h)) continue;

    datablockReserve(bx, by, w, h);
    mem->slot = (uint8_t)trySlot[i];

    // Leader from the blip to the block's near-inner corner.
    int lx = (bx > a.sx) ? bx : bx + w;
    int ly = (by > a.sy) ? by : by + h;
    spr.drawLine(a.sx, a.sy, lx, ly, dim ? BLOCK_TEXT_DIM : LEADER_LINE);

    uint16_t textCol = dim ? BLOCK_TEXT_DIM : BLOCK_TEXT;
    // The rare-airframe marker normally lives on the type field, which only
    // exists on line 2. Whenever line 2 is gone — the overview's callsign-only
    // form, or a block that lost the space to its neighbours — it moves onto
    // the callsign. Same glyphs, same ink, and the signal survives in exactly
    // the view that exists to choose what is worth a closer look.
    // Dim amber rather than bright white when stale: see TYPE_INTERESTING_DIM.
    // Brightness is the staleness channel and hue is the rarity channel, so a
    // block can say both at once — which the old "brighter when rare" form
    // could not do on a single-line block.
    uint16_t rareCol = dim ? TYPE_INTERESTING_DIM : TYPE_INTERESTING;
    bool rare = !radar::isCommonType(a.type);
    spr.setTextColor(!two && rare ? rareCol : textCol, TFT_BLACK);
    spr.drawString(cs, bx, by, 1);
    if (two) {
      int x = bx, y = by + CH_H + LINE_GAP;
      spr.setTextColor(textCol, TFT_BLACK);
      spr.drawString(alt, x, y, 1);
      x += textW(alt);
      if (hasArrow) {
        drawArrow(spr, x, y, climbing, textCol);
        x += ARROW_W;
      }
      if (type[0]) {
        x += CH_W / 2;
        // Colour here means "rare airframe" rather than altitude.
        spr.setTextColor(rare ? rareCol : textCol, TFT_BLACK);
        spr.drawString(type, x, y, 1);
      }
    }
    return true;
  }
  return false; // screen too crowded here — blip stands alone
}
