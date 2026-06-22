import { useState } from 'react';

interface Strategy {
  id: string;
  name: string;
  description: string;
}

interface StrategyCustomizerProps {
  strategies: Strategy[];
  enabled: Record<string, boolean>;
  onChange: (id: string, enabled: boolean) => void;
}

export function StrategyCustomizer({
  strategies,
  enabled,
  onChange,
}: StrategyCustomizerProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
  };

  return (
    <div className="strategy-customizer">
      <div className="strategy-header" onClick={toggleExpanded}>
        <span className="strategy-header-text">自定义策略</span>
        <span className={`strategy-toggle-icon ${isExpanded ? 'expanded' : ''}`}>
          ▸
        </span>
      </div>
      <div className={`strategy-list ${isExpanded ? 'expanded' : ''}`}>
        {strategies.map((strategy) => (
          <div key={strategy.id} className="strategy-item">
            <input
              type="checkbox"
              className="strategy-checkbox"
              checked={enabled[strategy.id] || false}
              onChange={(e) => onChange(strategy.id, e.target.checked)}
            />
            <div className="strategy-content">
              <div className="strategy-name">{strategy.name}</div>
              <div className="strategy-description">{strategy.description}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
