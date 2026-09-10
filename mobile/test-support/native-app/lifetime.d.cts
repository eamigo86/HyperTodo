import type { StorageQueue } from '../../src/realtime/session-effects';
export function createFixtureLifetime(credentials: {
  read(): Promise<string | null>;
  storage: StorageQueue;
}, themeIO: {
  read(): unknown;
  write(name: string): Promise<void>;
  clear(): Promise<void>;
}): {
  credentials: {
    read(): Promise<string | null>;
    storage: StorageQueue;
  };
  theme: {
    read(): unknown;
    write(name: string): void;
  };
  finish(): Promise<boolean>;
};
