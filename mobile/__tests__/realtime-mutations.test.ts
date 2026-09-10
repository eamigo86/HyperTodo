import {createMutationLedger} from '../src/realtime/mutations';

const A='a'.repeat(32),B='b'.repeat(32);
it('keeps correlating normal operations after more than32 fresh response seeds',()=>{
 const ledger=createMutationLedger();let latest='';
 for(let index=1;index<=40;index++){latest=index.toString(16).padStart(32,'0');expect(ledger.acceptSeed(latest)).toBe(true);}
 const id=ledger.admit({});expect(id).toBe(latest+'00000001');expect(ledger.isOwn(id)).toBe(true);
});
it('creates no identifier without a validated seed and never guesses local origin',()=>{
  const ledger=createMutationLedger(),op={};
  expect(ledger.admit(op)).toBeNull();
  for(const seed of [null,'a'.repeat(31),'A'.repeat(32),A+'\n'])expect(ledger.acceptSeed(seed)).toBe(false);
  expect(ledger.isOwn(null)).toBe(false);expect(ledger.isOwn(A+'00000001')).toBe(false);
  ledger.acceptSeed(A);expect(ledger.admit(op)).toBeNull();
  expect(ledger.admit({})).toBe(A+'00000001');
});

it('captures one immutable ID per admitted operation and retains its late echo without requiring a response',()=>{
  const ledger=createMutationLedger(),op={};ledger.acceptSeed(A);
  const id=ledger.admit(op);expect(id).toBe(A+'00000001');
  ledger.acceptSeed(B);expect(ledger.admit(op)).toBe(id);
  expect(ledger.isOwn(id)).toBe(true);
  expect(ledger.admit({})).toBe(B+'00000002');
  expect(ledger.isOwn(A+'00000002')).toBe(false);
});

it('does not restart counters on duplicate or out-of-order A→B→A seeds, even across a generation reset',()=>{
  const ledger=createMutationLedger();ledger.acceptSeed(A);
  const old=ledger.admit({});ledger.acceptSeed(A);expect(ledger.admit({})).toBe(A+'00000002');
  ledger.acceptSeed(B);expect(ledger.admit({})).toBe(B+'00000003');
  ledger.acceptSeed(A);expect(ledger.admit({})).toBe(A+'00000004');
  ledger.reset();expect(ledger.isOwn(old)).toBe(false);expect(ledger.admit({})).toBeNull();
  ledger.acceptSeed(A);expect(ledger.admit({})).toBe(A+'00000005');
});

it('fails to unknown at actual counter exhaustion without wrapping across a new seed or reset',()=>{
  const ledger=createMutationLedger({counterLimit:2});ledger.acceptSeed(A);
  expect(ledger.admit({})).toBe(A+'00000001');expect(ledger.admit({})).toBe(A+'00000002');
  expect(ledger.admit({})).toBeNull();ledger.acceptSeed(A);expect(ledger.admit({})).toBeNull();
  ledger.acceptSeed(B);expect(ledger.admit({})).toBeNull();
  ledger.reset();ledger.acceptSeed(A);expect(ledger.admit({})).toBeNull();
});

it('bounds remembered operations without retaining a seed history or reusing counters',()=>{
  const ledger=createMutationLedger({operationLimit:2});ledger.acceptSeed(A);
  const first=ledger.admit({}),second=ledger.admit({}),third=ledger.admit({});
  expect(ledger.isOwn(first)).toBe(false);expect(ledger.isOwn(second)).toBe(true);expect(ledger.isOwn(third)).toBe(true);
  ledger.acceptSeed(B);expect(ledger.acceptSeed('c'.repeat(32))).toBe(true);expect(ledger.admit({})).toBe('c'.repeat(32)+'00000004');
  ledger.acceptSeed(A);expect(ledger.admit({})).toBe(A+'00000005');
});
