/** Strip ElevenLabs v4 audio tags such as [laughs] or [half-laughing], also with punctuation inside. */
export function stripTags(text: string): string {
  return text
    .replace(/\[[^\]\n]{1,40}\]/g, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([,.!?])/g, "$1")
    .trim();
}

/** Does a finished reply end with a question (for the cow's questioning moo)? */
export function endsWithQuestion(text: string): boolean {
  return stripTags(text).trimEnd().endsWith("?");
}
