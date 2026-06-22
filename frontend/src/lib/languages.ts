// 语言元信息,与 backend/resources/language_settings/*.json 字段对齐
export const SUPPORTED_LANGUAGES = [
  { value: 'c', display: 'C', extension: 'c' },
  { value: 'cpp', display: 'C++', extension: 'cpp' },
  { value: 'python', display: 'Python', extension: 'py' },
  { value: 'java', display: 'Java', extension: 'java' },
  { value: 'go', display: 'Go', extension: 'go' },
] as const;

export type LanguageValue = typeof SUPPORTED_LANGUAGES[number]['value'];

export const LANGUAGE_MAP = Object.fromEntries(
  SUPPORTED_LANGUAGES.map(lang => [lang.value, lang])
) as Record<LanguageValue, typeof SUPPORTED_LANGUAGES[number]>;

export function getLanguageExtension(language: LanguageValue): string {
  return LANGUAGE_MAP[language]?.extension || 'txt';
}

export function getLanguageDisplay(language: LanguageValue): string {
  return LANGUAGE_MAP[language]?.display || language;
}
