import { createStreamDecoder } from '../src/realtime/stream-protocol';

const bytes = (value: string) => new TextEncoder().encode(value);
const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

it('decodes fragmented CRLF, UTF8 comments and multiple closed events without treating heartbeats as hints', () => {
  const events = jest.fn(), decoder = createStreamDecoder(events);
  const wire = bytes('\uFEFF: heartbeat 🌎\r\n\r\n' + frame('invalidate', {version:1,resources:['tasks','categories']}).replaceAll('\n','\r\n') + frame('resync',{version:1}) + frame('auth-required',{version:1}));
  for (const byte of wire) decoder.push(new Uint8Array([byte]));
  decoder.end();
  expect(events.mock.calls.map(([event]) => event)).toEqual([
    {type:'invalidate',resources:['tasks','categories']}, {type:'resync'}, {type:'auth-required'},
  ]);
  expect(Object.isFrozen(events.mock.calls[0][0])).toBe(true);
  expect(Object.isFrozen(events.mock.calls[0][0].resources)).toBe(true);
});

it.each(['tasks','categories','ui','tasks categories','tasks ui','categories ui','tasks categories ui'])('accepts the canonical resource combination %s', value => {
  const events=jest.fn(), decoder=createStreamDecoder(events);
  decoder.push(bytes(frame('invalidate',{version:1,resources:value.split(' ')})));
  expect(events).toHaveBeenCalledWith({type:'invalidate',resources:value.split(' ')});
});

it.each([
  ['invalidate',{version:1,resources:[]}], ['invalidate',{version:1,resources:['ui','tasks']}],
  ['invalidate',{version:1,resources:['tasks','tasks']}], ['invalidate',{version:1,resources:['owner']}],
  ['invalidate',{version:2,resources:['tasks']}], ['invalidate',{version:1,resources:['tasks'],url:'/private'}],
  ['resync',{version:1,resources:['tasks']}], ['auth-required',{version:1,owner:1}],
  ['resync',[]], ['message',{version:1}], ['invalidate',{resources:['tasks']}],
])('rejects unsupported event or payload %s %#', (event,data) => {
  const events=jest.fn(), decoder=createStreamDecoder(events);
  expect(() => decoder.push(bytes(frame(event as string,data)))).toThrow('invalid-stream');
  expect(events).not.toHaveBeenCalled();
});

it.each(['id: 1\n','retry: 1\n','other: x\n','event: invalidate\n'])('rejects commands/extra SSE fields %s', prefix => {
  const decoder=createStreamDecoder(jest.fn());
  expect(() => decoder.push(bytes(prefix+frame('resync',{version:1})))).toThrow('invalid-stream');
});

it('accepts multiline JSON and exactly4096 UTF8 data bytes, then bounds each frame independently', () => {
  const events=jest.fn(), decoder=createStreamDecoder(events);
  const json='{"version":1}';
  decoder.push(bytes(`event: resync\ndata: ${json}${' '.repeat(4096-json.length)}\n\n`));
  decoder.push(bytes('event: resync\ndata: {\ndata: "version":1}\n\n'));
  decoder.push(bytes(frame('resync',{version:1}).repeat(400)));
  expect(events).toHaveBeenCalledTimes(402);
  decoder.end();
});

it('rejects oversized JSON/buffers, malformed UTF8 and incomplete EOF without fabricating an event', () => {
  const cases = [
    bytes(`event: resync\ndata: {"version":1}${' '.repeat(4096)}\n\n`),
    bytes(':'+ 'x'.repeat(8192)),
    new Uint8Array([58,32,0xff,10,10]),
  ];
  for (const value of cases) {
    const events=jest.fn(), decoder=createStreamDecoder(events);
    expect(() => decoder.push(value)).toThrow('invalid-stream');
    expect(events).not.toHaveBeenCalled();
  }
  const events=jest.fn(), decoder=createStreamDecoder(events);
  decoder.push(bytes('event: resync\ndata: {"version":1}\n'));
  expect(() => decoder.end()).toThrow('invalid-stream');
  expect(events).not.toHaveBeenCalled();
});

it('uses the installed Expo57 decoder fatal/BOM semantics, not just the Node implementation', () => {
  // Test-only source compatibility control; production uses Expo's installed global.
  const {TextDecoder: ExpoDecoder} = jest.requireActual('expo/src/winter/TextDecoder');
  const original = globalThis.TextDecoder;
  globalThis.TextDecoder = ExpoDecoder;
  try {
    const events=jest.fn(), decoder=createStreamDecoder(events);
    const encoded=bytes('\uFEFF: 🌎\r\n\r\n'+frame('resync',{version:1}));
    for (const byte of encoded) decoder.push(new Uint8Array([byte]));
    decoder.end();
    expect(events).toHaveBeenCalledWith({type:'resync'});
    // Invalid leading byte, overlong encoding, surrogate and incomplete sequence.
    for (const invalid of [[0xff],[0xc0,0x80],[0xed,0xa0,0x80],[0xe2,0x82]]) {
      const rejected=jest.fn(), other=createStreamDecoder(rejected);
      expect(()=>other.push(new Uint8Array([58,32,...invalid,10,10]))).toThrow('invalid-stream');
      expect(rejected).not.toHaveBeenCalled();
    }
  } finally { globalThis.TextDecoder=original; }
});
