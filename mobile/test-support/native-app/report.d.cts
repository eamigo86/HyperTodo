export type CaseName = 'startup' | 'auth' | 'resources' | 'form' | 'append-race' | 'post-race' | 'lifecycle' | 'refusal' | 'cleanup';
export type ReportPart = {
  case: CaseName;
  kind: string;
  operation?: string | null;
  route?: number | null;
  outcome?: string | null;
  reason?: string | null;
};
export type NativeRecord = {
  v: 1;
  run: string;
  sequence: number;
  platform: 'ios' | 'android';
  case: CaseName;
  kind: string;
  operation: string | null;
  route: number | null;
  outcome: string | null;
  reason: string | null;
};
export function validateRecord(input: unknown, run: string, sequence: number): Readonly<NativeRecord>;
export function createReporter(run: string, platform: 'ios' | 'android', upload: (record: Readonly<NativeRecord>, signal: AbortSignal) => Promise<number>): {
  send(part: ReportPart): boolean;
  setActive(active: boolean): void;
  dispose(): void;
  settled(): Promise<void>;
  complete(): Promise<string>;
  records(): readonly Readonly<NativeRecord>[];
  snapshot(): Readonly<{
    state: string;
    reason: string | null;
    records: number;
  }>;
};
export const CASES: readonly CaseName[];
