export function createResponseHold(http: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>, observe: (event: {
  kind: string;
  operation?: string;
  reason?: string;
}) => void): {
  fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
  arm(method: 'get' | 'post'): boolean;
  release(): boolean;
  dispose(): void;
  snapshot(): string;
};
