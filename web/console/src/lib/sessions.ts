export function newSessionId(): string {
  return `sess_${crypto.randomUUID()}`;
}
