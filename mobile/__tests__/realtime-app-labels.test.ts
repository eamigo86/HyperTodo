import { sessionLabels } from '../src/realtime/app-session-labels';
it('resolves real Content-Language ES and EN while preserving uncertainty in hints', () => {
  expect(sessionLabels('es').changed).toBe('Puede haber cambios');
  expect(sessionLabels('es-AR').changed).toBe('Puede haber cambios');
  expect(sessionLabels('en').changed).toBe('There may be changes');
  expect(sessionLabels('es').resync).toBe('Necesitamos comprobar el estado actual');
  expect(sessionLabels(null)).toEqual(sessionLabels('en'));
  expect(sessionLabels('private or unsupported')).toEqual(sessionLabels('en'));
});
