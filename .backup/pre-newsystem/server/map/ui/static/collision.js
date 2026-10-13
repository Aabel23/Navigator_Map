// Which labels actually get drawn.
//
// A map with every label drawn is unreadable: names pile on top of names and
// none of them can be read. Deciding what to drop is most of what a label
// engine does, and it has to be redone whenever the camera moves, because two
// labels that were far apart at one zoom overlap at another.
//
// The rule is simple and the same one paper cartographers use: sort by
// importance, then place greedily -- a label is drawn if its box is still
// clear when its turn comes, and dropped if it is not. Nothing is ever moved
// to make room, because a label that slides around as the camera pans is more
// distracting than a label that is missing.
//
// The index is a uniform grid rather than a tree. Labels are screen-sized and
// roughly evenly spread, which is exactly the case a grid handles well and a
// tree only complicates.

const CELL_SIZE = 96;

export class CollisionGrid {
  /**
   * @param {number} width - viewport width in CSS pixels.
   * @param {number} height
   */
  constructor(width, height) {
    this.cols = Math.max(1, Math.ceil(width / CELL_SIZE));
    this.rows = Math.max(1, Math.ceil(height / CELL_SIZE));
    /** @type {Array<Array<number[]>>} cell -> list of [x1,y1,x2,y2] */
    this.cells = new Array(this.cols * this.rows);
  }

  _range(box) {
    return {
      c0: Math.max(0, Math.floor(box[0] / CELL_SIZE)),
      c1: Math.min(this.cols - 1, Math.floor(box[2] / CELL_SIZE)),
      r0: Math.max(0, Math.floor(box[1] / CELL_SIZE)),
      r1: Math.min(this.rows - 1, Math.floor(box[3] / CELL_SIZE)),
    };
  }

  /** Is this box clear of everything placed so far? */
  fits(box) {
    const { c0, c1, r0, r1 } = this._range(box);
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        const bucket = this.cells[r * this.cols + c];
        if (!bucket) continue;
        for (const other of bucket) {
          if (box[0] < other[2] && box[2] > other[0] && box[1] < other[3] && box[3] > other[1]) {
            return false;
          }
        }
      }
    }
    return true;
  }

  /** Claim this box, so later labels have to work around it. */
  insert(box) {
    const { c0, c1, r0, r1 } = this._range(box);
    for (let r = r0; r <= r1; r++) {
      for (let c = c0; c <= c1; c++) {
        const key = r * this.cols + c;
        const bucket = this.cells[key];
        if (bucket) bucket.push(box);
        else this.cells[key] = [box];
      }
    }
  }
}

/**
 * The screen-space box of a label whose text is rotated about its anchor.
 *
 * A rotated rectangle is approximated by its axis-aligned bounds. That is
 * generous for a diagonal street name, which is the right way to be wrong:
 * two labels are kept apart slightly more often than strictly necessary,
 * rather than being allowed to clip each other.
 */
export function rotatedBounds(centreX, centreY, width, height, angle, padding) {
  const cos = Math.abs(Math.cos(angle));
  const sin = Math.abs(Math.sin(angle));
  const halfW = (width * cos + height * sin) / 2 + padding;
  const halfH = (width * sin + height * cos) / 2 + padding;
  return [centreX - halfW, centreY - halfH, centreX + halfW, centreY + halfH];
}
