// Чтение ZIP-архивов (для импорта сборников задач целиком). Поддерживаются методы store и deflate.
export async function readZip(buf) {
  const bytes = new Uint8Array(buf);
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let eocd = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("это не ZIP-архив");
  const count = dv.getUint16(eocd + 10, true);
  let off = dv.getUint32(eocd + 16, true);
  const out = [];
  for (let k = 0; k < count; k++) {
    if (dv.getUint32(off, true) !== 0x02014b50) break;
    const method = dv.getUint16(off + 10, true);
    const flags = dv.getUint16(off + 8, true);
    const csize = dv.getUint32(off + 20, true);
    const nameLen = dv.getUint16(off + 28, true);
    const extraLen = dv.getUint16(off + 30, true);
    const commentLen = dv.getUint16(off + 32, true);
    const local = dv.getUint32(off + 42, true);
    const nameBytes = bytes.subarray(off + 46, off + 46 + nameLen);
    let name;
    try { name = new TextDecoder(flags & 0x800 ? "utf-8" : "utf-8", { fatal: true }).decode(nameBytes); }
    catch { name = new TextDecoder("ibm866").decode(nameBytes); }
    off += 46 + nameLen + extraLen + commentLen;
    if (name.endsWith("/")) continue;
    const lnameLen = dv.getUint16(local + 26, true), lextra = dv.getUint16(local + 28, true);
    const start = local + 30 + lnameLen + lextra;
    const data = bytes.subarray(start, start + csize);
    out.push({ name, method, data });
  }
  return out;
}

export async function inflate(entry) {
  if (entry.method === 0) return entry.data;
  if (entry.method !== 8) throw new Error("неподдерживаемое сжатие");
  const stream = new Blob([entry.data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
