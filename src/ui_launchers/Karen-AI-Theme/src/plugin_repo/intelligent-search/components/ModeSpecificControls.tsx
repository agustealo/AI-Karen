import React from 'react';
import { SlidersHorizontal } from 'lucide-react';
import { ModeConfigItem } from '../configs/modeConfig';
import { IntelligentSearchOptions } from '../types';

interface ModeSpecificControlsProps {
  modeConfig: ModeConfigItem;
  options: IntelligentSearchOptions;
  onOptionsChange: (options: Partial<IntelligentSearchOptions>) => void;
  disabled?: boolean;
}

export function ModeSpecificControls({ modeConfig, options, onOptionsChange, disabled }: ModeSpecificControlsProps) {
  const visible = modeConfig.visibleControls;

  const renderInput = (field: keyof IntelligentSearchOptions, label: string, type: string = 'text', placeholder?: string) => {
    if (!visible.includes(field)) return null;

    const value = options[field] as any;
    
    if (type === 'checkbox') {
      return (
        <div key={field} className="flex items-center gap-2">
          <input
            type="checkbox"
            id={`chk-${field}`}
            checked={!!value}
            disabled={disabled}
            onChange={(e) => onOptionsChange({ [field]: e.target.checked })}
            className="w-4 h-4 rounded border-border text-primary focus:ring-primary disabled:opacity-50"
          />
          <label htmlFor={`chk-${field}`} className="text-sm text-foreground">{label}</label>
        </div>
      );
    }

    return (
      <div key={field} className="space-y-1">
        <label className="text-xs font-medium text-foreground">{label}</label>
        <input
          type={type}
          value={value || ''}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(e) => onOptionsChange({ 
            [field]: type === 'number' ? parseInt(e.target.value) || undefined : e.target.value 
          })}
          className="w-full bg-background border border-border px-3 py-1.5 rounded-md text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary transition-all disabled:opacity-50"
        />
      </div>
    );
  };

  if (!visible || visible.length === 0) return null;

  return (
    <div className="space-y-4 rounded-3xl border border-border/60 bg-card/80 p-4 shadow-sm">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
        <SlidersHorizontal className="h-3.5 w-3.5 text-primary" />
        {modeConfig.label} options
      </div>
      <div className="space-y-3">
        {/* General */}
        {renderInput('maxUrls', 'Max URLs', 'number')}
        {renderInput('freshnessBias', 'Freshness Bias')}
        {/* We simplify arrays to comma separated strings for now */}
        {renderInput('allowedDomains', 'Allowed Domains')}
        {renderInput('blockedDomains', 'Blocked Domains')}

        {/* News */}
        {renderInput('timeRange', 'Time Range (e.g. 24h, 7d)')}
        {renderInput('preferRecent', 'Prefer Recent', 'checkbox')}

        {/* Docs */}
        {renderInput('product', 'Product')}
        {renderInput('version', 'Version')}
        {renderInput('officialOnly', 'Official Only', 'checkbox')}
        
        {/* Deep Research */}
        {renderInput('maxSubqueries', 'Max Subqueries', 'number')}
        {renderInput('maxHops', 'Max Hops', 'number')}
        
        {/* Structured Extract */}
        {renderInput('schema', 'Target Schema')}
        {renderInput('instruction', 'Extraction Instruction')}

        {/* Weather */}
        {renderInput('location', 'Location')}
        {renderInput('units', 'Units')}
        {renderInput('includeCurrent', 'Include Current', 'checkbox')}
        {renderInput('includeHourly', 'Include Hourly', 'checkbox')}

        {/* Stock */}
        {renderInput('ticker', 'Ticker')}
        {renderInput('companyName', 'Company Name')}
        {renderInput('includePriceAction', 'Include Price Action', 'checkbox')}
        {renderInput('includeCompanyNews', 'Include Company News', 'checkbox')}
      </div>
    </div>
  );
}
