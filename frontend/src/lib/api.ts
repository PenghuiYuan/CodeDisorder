// Fetch wrapper with error handling
const API_BASE = '/api';

export interface ApiError {
  code: string;
  stage: string;
  message: string;
  errors: Array<{ line: number; column: number; message: string }>;
}

export interface Preset {
  id: string;
  display: string;
  strength: 'weak' | 'medium' | 'strong';
  description: string;
  strategies: Record<string, boolean | string>;
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  applicable_languages: string[];
  mutually_exclusive_with?: string[];
}

interface StrategyCatalogItem {
  key: string;
  values: string[];
  default: string | null;
}

interface StrategiesResponse {
  strategies: StrategyCatalogItem[];
}

export interface PresetsResponse {
  presets: Preset[];
  custom?: {
    display: string;
    strategies: Record<string, boolean | string>;
  };
}

export interface ConfuseRequest {
  language_in: string;
  language_out: string;
  preset: string;
  count: number;
  overrides?: Record<string, boolean | string>;
  code: string;
}

export interface ConfuseResponseSuccess {
  status: 'ok';
  language_in: string;
  language_out: string;
  preset: string;
  count: number;
  applied: string[];
  code?: string;
  zip_b64?: string;
  verify: 'compiled' | 'syntax-ok' | 'warning';
  failed_indexes?: number[];
}

export interface ConfuseResponseError {
  status: 'error';
  code: string;
  stage: string;
  message: string;
  errors: Array<{ line: number; column: number; message: string }>;
}

export type ConfuseResponse = ConfuseResponseSuccess | ConfuseResponseError;

const STRATEGY_META: Record<string, { name: string; description: string }> = {
  rename: {
    name: '标识符改名',
    description: '重命名变量、函数、参数等用户定义符号。',
  },
  literalRewrite: {
    name: '字面量改写',
    description: '将部分数字字面量改写为等价表达式。',
  },
  splitExpression: {
    name: '表达式拆分',
    description: '拆分简单表达式，改变局部 AST 形状。',
  },
  shuffleIncludes: {
    name: '导入顺序随机',
    description: '随机调整顶部 include/import 块顺序。',
  },
  stripComments: {
    name: '剥离注释',
    description: '去除注释并保留代码行号结构。',
  },
};

export async function getMeta(): Promise<PresetsResponse> {
  const response = await fetch(`${API_BASE}/presets`);
  if (!response.ok) {
    throw new Error(`Failed to fetch meta: ${response.statusText}`);
  }
  return response.json();
}

export async function getStrategies(): Promise<Strategy[]> {
  const response = await fetch(`${API_BASE}/strategies`);
  if (!response.ok) {
    throw new Error(`Failed to fetch strategies: ${response.statusText}`);
  }
  const data = (await response.json()) as StrategiesResponse;
  return data.strategies
    .filter((item) => item.values.includes('true') || item.values.includes('false'))
    .map((item) => {
      const meta = STRATEGY_META[item.key] || {
        name: item.key,
        description: '自定义策略开关。',
      };
      return {
        id: item.key,
        name: meta.name,
        description: meta.description,
        applicable_languages: ['c', 'cpp', 'python'],
      };
    });
}

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.statusText}`);
  }
  return response.json();
}

export async function postConfuse(
  request: ConfuseRequest
): Promise<ConfuseResponse> {
  const response = await fetch(`${API_BASE}/confuse`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.statusText}`);
  }

  return response.json();
}
