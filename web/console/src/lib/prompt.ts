/** Insert a saved prompt into a draft: use `text` alone when the draft is
 *  empty, otherwise append it after a blank line. Pure. */
export function appendPrompt(existing: string, text: string): string {
  return existing.trim() ? `${existing}\n\n${text}` : text;
}
