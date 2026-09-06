export type SnackbarTone = "success" | "error";

export type SnackbarNotice = {
  message: string;
  tone: SnackbarTone;
};

type SnackbarListener = (notice: SnackbarNotice) => void;

const listeners = new Set<SnackbarListener>();

export function publishSnackbar(notice: SnackbarNotice): void {
  listeners.forEach((listener) => listener(notice));
}

export function subscribeToSnackbars(listener: SnackbarListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
