import { useState, useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TopBar } from './components/TopBar';
import { EditorPanel } from './components/EditorPanel';
import { ControlBar } from './components/ControlBar';
import { StatusBar } from './components/StatusBar';
import { useMeta } from './hooks/useMeta';
import { useConfuse } from './hooks/useConfuse';
import { getLanguageExtension, type LanguageValue } from './lib/languages';
import './styles/global.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function AppContent() {
  const { presets, strategies, isHealthy } = useMeta();
  const { confuse, isRunning, result, reset } = useConfuse();

  const [sourceCode, setSourceCode] = useState('');
  const [sourceLanguage, setSourceLanguage] = useState<LanguageValue>('cpp');
  const [targetLanguage, setTargetLanguage] = useState<LanguageValue>('cpp');
  const [selectedPreset, setSelectedPreset] = useState('default');
  const [selectedCount, setSelectedCount] = useState(1);
  const [customStrategies, setCustomStrategies] = useState<Record<string, boolean>>({});
  const [resultCode, setResultCode] = useState('');
  const [resultStatus, setResultStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');
  const [toast, setToast] = useState<string | null>(null);

  // 目标语言与源语言同步
  useEffect(() => {
    setTargetLanguage(sourceLanguage);
  }, [sourceLanguage]);

  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(null), 3000);
  };

  const handleClear = () => {
    setSourceCode('');
    setResultCode('');
    setResultStatus('idle');
    reset();
  };

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      setSourceCode(text);
    } catch (err) {
      showToast('粘贴失败,请检查浏览器权限');
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(resultCode);
    showToast('已复制到剪贴板');
  };

  const handleDownloadSingle = () => {
    const extension = getLanguageExtension(targetLanguage);
    const blob = new Blob([resultCode], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `confused.${extension}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleDownloadZip = () => {
    if (!result || result.status !== 'ok') {
      return;
    }

    if (result.zip_b64) {
      const binaryString = atob(result.zip_b64);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      const blob = new Blob([bytes], { type: 'application/zip' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'confused.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } else {
      showToast('批量功能 M2 上线');
    }
  };

  const handleStart = () => {
    if (!sourceCode.trim()) {
      showToast('请输入源代码');
      return;
    }

    const charCount = new TextEncoder().encode(sourceCode).length;
    if (charCount > 200 * 1024) {
      showToast('代码超过 200KB 上限');
      return;
    }

    setResultStatus('running');
    setResultCode('');

    confuse({
      language_in: sourceLanguage,
      language_out: targetLanguage,
      preset: selectedPreset,
      count: selectedCount,
      overrides: customStrategies,
      code: sourceCode,
    });
  };

  // 处理混淆结果
  useEffect(() => {
    if (!result) return;

    if (result.status === 'ok') {
      setResultStatus('success');
      if (result.code) {
        setResultCode(result.code);
      } else if (selectedCount > 1) {
        // 批量模式时显示第一个结果(如果有)或占位文本
        setResultCode('// 批量生成完成,请下载 .zip 文件');
      }
    } else if (result.status === 'error') {
      setResultStatus('error');
      setResultCode(`// 错误: ${result.message}\n// 阶段: ${result.stage}`);
    }
  }, [result, selectedCount]);

  const canStart =
    sourceCode.trim().length > 0 &&
    new TextEncoder().encode(sourceCode).length <= 200 * 1024 &&
    !isRunning &&
    isHealthy;

  const failedCount = result?.status === 'ok' ? (result.failed_indexes?.length || 0) : 0;
  const successCount = result?.status === 'ok' ? selectedCount - failedCount : 0;

  return (
    <>
      {toast && <div className="toast">{toast}</div>}
      <TopBar />
      <div className="main-layout">
        <EditorPanel
          mode="source"
          language={sourceLanguage}
          onLanguageChange={(language) => setSourceLanguage(language as LanguageValue)}
          value={sourceCode}
          onChange={setSourceCode}
          onClear={handleClear}
          onPaste={handlePaste}
        />

        <ControlBar
          presets={presets}
          strategies={strategies}
          onStart={handleStart}
          isRunning={isRunning}
          canStart={canStart}
          selectedPreset={selectedPreset}
          onPresetChange={setSelectedPreset}
          selectedCount={selectedCount}
          onCountChange={setSelectedCount}
          customStrategies={customStrategies}
          onStrategyToggle={(id, enabled) =>
            setCustomStrategies((prev) => ({ ...prev, [id]: enabled }))
          }
        />

        <EditorPanel
          mode="result"
          language={targetLanguage}
          value={resultCode}
          readOnly
          onCopy={handleCopy}
          onDownloadSingle={handleDownloadSingle}
          onDownloadZip={handleDownloadZip}
          resultStatus={resultStatus}
          batchCount={successCount}
          batchSize={selectedCount}
        />
      </div>
      <StatusBar />
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
