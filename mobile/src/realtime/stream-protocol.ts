import { parseResources, type ResourceName } from './resources';
import { utf8Bytes } from './session-protocol';

export type StreamEvent = Readonly<{type:'invalidate'; resources:readonly ResourceName[]}> | Readonly<{type:'resync'}> | Readonly<{type:'auth-required'}>;

function eventValue(type: string, body: string): StreamEvent {
  const value: unknown = JSON.parse(body);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid-stream');
  const data = value as Record<string, unknown>;
  const keys = Object.keys(data).sort().join(',');
  if (data.version !== 1) throw new Error('invalid-stream');
  if (type === 'invalidate' && keys === 'resources,version') {
    const resources = parseResources(data.resources);
    if (resources) return Object.freeze({type, resources});
  } else if ((type === 'resync' || type === 'auth-required') && keys === 'version') {
    return Object.freeze({type});
  }
  throw new Error('invalid-stream');
}

/** Closed application SSE protocol, not a replay-capable generic EventSource. */
export function createStreamDecoder(deliver: (event: StreamEvent) => void) {
  const decoder = new TextDecoder('utf-8', {fatal:true, ignoreBOM:true});
  let line: number[] = [], data: string[] = [], type = '';
  let dataBytes = 0, frameBytes = 0, firstLine = true, skipLF = false, ended = false;
  const bad = (): never => { ended = true; throw new Error('invalid-stream'); };
  function consumeLine() {
    let text = decoder.decode(new Uint8Array(line));
    line = [];
    if (firstLine && text.startsWith('\uFEFF')) text = text.slice(1);
    firstLine = false;
    if (!text) {
      if (type || data.length) {
        if (!type || !data.length) bad();
        const event = eventValue(type, data.join('\n'));
        type = ''; data = []; dataBytes = 0; frameBytes = 0;
        deliver(event);
      }
      frameBytes = 0;
      return;
    }
    if (text.startsWith(':')) return;
    const colon = text.indexOf(':');
    const field = colon < 0 ? text : text.slice(0, colon);
    let value = colon < 0 ? '' : text.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event' && !type) {
      if (!['invalidate','resync','auth-required'].includes(value)) bad();
      type = value;
    } else if (field === 'data') {
      dataBytes += utf8Bytes(value) + (data.length ? 1 : 0);
      if (dataBytes > 4096) bad();
      data.push(value);
    } else bad(); // id/retry and unknown fields cannot create replay behavior.
  }
  return {
    push(chunk: Uint8Array): void {
      if (ended || !(chunk instanceof Uint8Array)) bad();
      try {
        // Consume large native chunks incrementally; never concatenate their full text.
        for (const byte of chunk) {
          if (skipLF) {
            skipLF = false;
            if (byte === 10) { if (frameBytes && ++frameBytes > 8192) bad(); continue; }
          }
          if (++frameBytes > 8192) bad();
          if (byte === 10 || byte === 13) {
            consumeLine(); skipLF = byte === 13;
          } else line.push(byte);
        }
      } catch { bad(); }
    },
    end(): void {
      if (ended || line.length || type || data.length) bad();
      ended = true;
    },
  };
}
