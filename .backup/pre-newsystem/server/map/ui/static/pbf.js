// The three protobuf primitives every decoder in this block needs.
//
// Vector tiles and glyph ranges are both protobuf, and both are walked the
// same way: read a key, split it into a field number and a wire type, then
// either read the value or skip past it. Keeping that here means there is one
// varint reader in the block rather than one per format.

/** Read an unsigned varint at `i`. Returns `[value, nextIndex]`. */
export function readUVarint(buf, i) {
  let result = 0;
  let shift = 0;
  for (;;) {
    const byte = buf[i];
    i += 1;
    result |= (byte & 0x7f) << shift;
    if (!(byte & 0x80)) return [result >>> 0, i];
    shift += 7;
  }
}

/** Undo protobuf's zigzag encoding of a signed integer. */
export function unzigzag(value) {
  return (value >>> 1) ^ -(value & 1);
}

/** Skip the value of a field whose key has already been read. */
export function skipField(buf, i, wire) {
  if (wire === 0) return readUVarint(buf, i)[1];
  if (wire === 2) {
    const [len, next] = readUVarint(buf, i);
    return next + len;
  }
  if (wire === 5) return i + 4;
  if (wire === 1) return i + 8;
  throw new Error(`unsupported wire type ${wire}`);
}
