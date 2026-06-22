import { useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { SUPPORTED_LANGUAGES, getLanguageDisplay } from '../lib/languages';

interface EditorPanelProps {
  mode: 'source' | 'result';
  language: string;
  onLanguageChange?: (language: string) => void;
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  onClear?: () => void;
  onPaste?: () => void;
  onCopy?: () => void;
  onDownloadSingle?: () => void;
  onDownloadZip?: () => void;
  resultStatus?: 'idle' | 'running' | 'success' | 'error';
  batchCount?: number;
  batchSize?: number;
}

export function EditorPanel({
  mode,
  language,
  onLanguageChange,
  value,
  onChange,
  readOnly = false,
  onClear,
  onPaste,
  onCopy,
  onDownloadSingle,
  onDownloadZip,
  resultStatus = 'idle',
  batchCount = 0,
  batchSize = 0,
}: EditorPanelProps) {
  const [charCount, setCharCount] = useState(0);
  const [isOverLimit, setIsOverLimit] = useState(false);

  useEffect(() => {
    const bytes = new TextEncoder().encode(value).length;
    setCharCount(bytes);
    setIsOverLimit(bytes > 200 * 1024);
  }, [value]);

  const handleEditorChange = (newValue: string | undefined) => {
    if (onChange && newValue !== undefined) {
      onChange(newValue);
    }
  };

  const showBatchInfo = mode === 'result' && resultStatus === 'success' && batchSize > 1;
  const showCopyButton = mode === 'result' && resultStatus === 'success' && batchSize === 1;
  const showDownloadSingle = mode === 'result' && resultStatus === 'success' && batchSize === 1;
  const showDownloadZip = mode === 'result' && resultStatus === 'success' && batchSize > 1;

  let displayValue = value;
  if (mode === 'result' && resultStatus === 'idle' && !value) {
    displayValue = '// 等待混淆结果...';
  }

  return (
    <div className={`editor-panel ${isOverLimit && mode === 'source' ? 'error' : ''}`}>
      <div className="editor-header">
        <div className="editor-controls">
          <span className="control-label">
            {mode === 'source' ? '源语言' : '目标语言'}:
          </span>
          <select
            className="language-select"
            value={language}
            disabled={readOnly}
            onChange={(event) => onLanguageChange?.(event.target.value)}
          >
            {SUPPORTED_LANGUAGES.map((lang) => (
              <option key={lang.value} value={lang.value}>
                {getLanguageDisplay(lang.value)}
              </option>
            ))}
          </select>
          <span className={`char-count ${isOverLimit ? 'error' : ''}`}>
            (字符数 {charCount.toLocaleString()})
          </span>
        </div>
      </div>

      {mode === 'source' && (
        <div className="editor-toolbar">
          <button className="button" onClick={onClear}>
            清空
          </button>
          <button className="button" onClick={onPaste}>
            粘贴
          </button>
        </div>
      )}

      <div className={`monaco-container ${isOverLimit && mode === 'source' ? 'error' : ''}`}>
        <Editor
          height="100%"
          language={language}
          value={displayValue}
          onChange={!readOnly ? handleEditorChange : undefined}
          options={{
            readOnly,
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            wordWrap: 'on',
          }}
        />
      </div>

      {mode === 'result' && (
        <>
          {showBatchInfo && (
            <div className="batch-info">
              已生成 {batchCount} 个变体 {batchSize > batchCount && `(共 ${batchSize} 个请求)`}
            </div>
          )}
          <div className="result-toolbar">
            {showCopyButton && (
              <button className="button" onClick={onCopy}>
                复制
              </button>
            )}
            {showDownloadSingle && (
              <button className="button" onClick={onDownloadSingle}>
                下载单文件
              </button>
            )}
            {showDownloadZip && (
              <button className="button" onClick={onDownloadZip}>
                下载 .zip
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
