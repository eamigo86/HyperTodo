/** Public UI copy selected from an owned server Content-Language, never profile data. */
const EN = Object.freeze({
  changed: 'There may be changes',
  resync: 'We need to check the current state',
  update: 'Update',
  csrf: 'Your session could not verify this request. Your changes are still here. Try again.',
  error: 'Could not update. Try again.',
  shield: 'Session protection',
  paused: 'Session paused',
  confirming: 'Confirming your session',
  unconfirmed: 'We could not confirm your session',
  retry: 'Retry session confirmation',
  signIn: 'Sign in'
});
const ES = Object.freeze({
  changed: 'Puede haber cambios',
  resync: 'Necesitamos comprobar el estado actual',
  update: 'Actualizar',
  csrf: 'No pudimos verificar esta solicitud. Tus cambios siguen acá. Intentá de nuevo.',
  error: 'No pudimos actualizar. Intentá de nuevo.',
  shield: 'Protección de sesión',
  paused: 'Sesión en pausa',
  confirming: 'Confirmando tu sesión',
  unconfirmed: 'No pudimos confirmar tu sesión',
  retry: 'Volver a comprobar la sesión',
  signIn: 'Iniciar sesión'
});
export function sessionLabels(language: string | null) {
  return typeof language === 'string' && /^es(?:-[a-z0-9]+)*$/i.test(language) ? ES : EN;
}
