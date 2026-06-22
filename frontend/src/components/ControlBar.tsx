import { StrategyCustomizer } from './StrategyCustomizer';
import type { Preset, Strategy } from '../lib/api';

interface ControlBarProps {
  presets: Preset[];
  strategies: Strategy[];
  onStart: () => void;
  isRunning: boolean;
  canStart: boolean;
  selectedPreset: string;
  onPresetChange: (preset: string) => void;
  selectedCount: number;
  onCountChange: (count: number) => void;
  customStrategies: Record<string, boolean>;
  onStrategyToggle: (id: string, enabled: boolean) => void;
}

export function ControlBar({
  presets,
  strategies,
  onStart,
  isRunning,
  canStart,
  selectedPreset,
  onPresetChange,
  selectedCount,
  onCountChange,
  customStrategies,
  onStrategyToggle,
}: ControlBarProps) {
  const countOptions = [1, 3, 5, 10];

  return (
    <div className="control-bar">
      <div className="control-group">
        <label className="control-label">OJ 预设</label>
        <select
          className="control-select"
          value={selectedPreset}
          onChange={(e) => onPresetChange(e.target.value)}
          disabled={isRunning}
        >
          {presets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.display}
            </option>
          ))}
        </select>
        <div className="control-hint">
          {presets.find((p) => p.id === selectedPreset)?.description}
        </div>
      </div>

      <div className="control-group">
        <label className="control-label">生成数量</label>
        <select
          className="control-select"
          value={selectedCount}
          onChange={(e) => onCountChange(Number(e.target.value))}
          disabled={isRunning}
        >
          {countOptions.map((count) => (
            <option key={count} value={count}>
              {count}
            </option>
          ))}
        </select>
        {selectedCount > 1 && (
          <div className="control-hint">
            批量生成较慢,只支持 .zip 下载
          </div>
        )}
      </div>

      <StrategyCustomizer
        strategies={strategies}
        enabled={customStrategies}
        onChange={onStrategyToggle}
      />

      <button
        className="button button-primary control-button"
        onClick={onStart}
        disabled={!canStart || isRunning}
      >
        {isRunning ? '混淆中...' : '开始混淆'}
      </button>

      {isRunning && (
        <div className="control-hint">
          正在生成混淆代码...
        </div>
      )}
    </div>
  );
}
