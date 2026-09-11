/** Public UI copy selected from an owned server Content-Language, never profile data. */
const EN = Object.freeze({
  changed: 'There may be changes',
  resync: 'We need to check the current state',
  update: 'Update',
  conflict: Object.freeze({messages:Object.freeze({task:'This task was updated remotely.',category:'This category was updated remotely.',settings:'These settings were updated remotely.',form:'This form was updated remotely.'}),goBack:'Go back',backUnavailable:'The previous page is unavailable or has unsaved edits.'}),
  updated: 'Updated with recent changes',
  dismiss: 'Dismiss notice',
  discardTitle: 'Discard unsaved edits?',
  discardMessage: 'Reloading replaces the form with its current saved values. Your unsaved edits will be lost.',
  keepEditing: 'Keep editing',
  discardChanges: 'Discard and reload',
  newerEdits: 'Your newer edits are still here. Discard them to show the server response.',
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
  conflict: Object.freeze({messages:Object.freeze({task:'Los datos de esta tarea se modificaron de forma remota.',category:'Los datos de esta categoría se modificaron de forma remota.',settings:'Esta configuración se modificó de forma remota.',form:'Los datos de este formulario se modificaron de forma remota.'}),goBack:'Volver',backUnavailable:'La página anterior no está disponible o tiene cambios sin guardar.'}),
  updated: 'Actualizado con los cambios recientes',
  dismiss: 'Cerrar aviso',
  discardTitle: '¿Descartar los cambios sin guardar?',
  discardMessage: 'Al recargar, el formulario se reemplaza por los valores guardados actuales. Vas a perder los cambios sin guardar.',
  keepEditing: 'Seguir editando',
  discardChanges: 'Descartar y recargar',
  newerEdits: 'Tus cambios más recientes siguen acá. Descartalos para mostrar la respuesta del servidor.',
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
