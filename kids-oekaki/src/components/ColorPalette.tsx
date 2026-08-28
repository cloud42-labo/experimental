import { useMemo, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

const QUICK_COLORS = ['#111111', '#ffffff', '#e03131', '#f08c00', '#f6c90e', '#2f9e44', '#1098ad', '#1971c2', '#7048e8', '#c2255c'];
const SWATCHES = [
  '#000000', '#343a40', '#868e96', '#ced4da', '#ffffff',
  '#c92a2a', '#e03131', '#f03e3e', '#ff8787', '#ffc9c9',
  '#e8590c', '#f76707', '#fd7e14', '#ffa94d', '#ffd8a8',
  '#e67700', '#f59f00', '#fab005', '#ffd43b', '#fff3bf',
  '#2b8a3e', '#37b24d', '#51cf66', '#8ce99a', '#d3f9d8',
  '#0b7285', '#0c8599', '#15aabf', '#66d9e8', '#c5f6fa',
  '#1864ab', '#1971c2', '#339af0', '#74c0fc', '#d0ebff',
  '#5f3dc4', '#7048e8', '#845ef7', '#b197fc', '#e5dbff',
  '#a61e4d', '#c2255c', '#e64980', '#f783ac', '#ffdeeb',
];

type Tab = 'wheel' | 'swatches' | 'sliders';

type Props = {
  color: string;
  recentColors: string[];
  eyedropperActive: boolean;
  onColorChange: (color: string) => void;
  onEyedropper: () => void;
};

type RGB = { r: number; g: number; b: number };
type HSV = { h: number; s: number; v: number };

function normalizeHex(value: string) {
  const raw = value.trim().replace(/^#/, '');
  if (/^[0-9a-fA-F]{6}$/.test(raw)) return `#${raw.toLowerCase()}`;
  if (/^[0-9a-fA-F]{3}$/.test(raw)) return `#${raw.split('').map((c) => c + c).join('').toLowerCase()}`;
  return null;
}

function hexToRgb(hex: string): RGB {
  const normalized = normalizeHex(hex) ?? '#000000';
  return {
    r: parseInt(normalized.slice(1, 3), 16),
    g: parseInt(normalized.slice(3, 5), 16),
    b: parseInt(normalized.slice(5, 7), 16),
  };
}

function rgbToHex({ r, g, b }: RGB) {
  return `#${[r, g, b].map((value) => Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, '0')).join('')}`;
}

function rgbToHsv({ r, g, b }: RGB): HSV {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const delta = max - min;
  let h = 0;
  if (delta !== 0) {
    if (max === rn) h = 60 * (((gn - bn) / delta) % 6);
    else if (max === gn) h = 60 * ((bn - rn) / delta + 2);
    else h = 60 * ((rn - gn) / delta + 4);
  }
  if (h < 0) h += 360;
  return { h, s: max === 0 ? 0 : delta / max, v: max };
}

function hsvToRgb({ h, s, v }: HSV): RGB {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  let base: [number, number, number];
  if (h < 60) base = [c, x, 0];
  else if (h < 120) base = [x, c, 0];
  else if (h < 180) base = [0, c, x];
  else if (h < 240) base = [0, x, c];
  else if (h < 300) base = [x, 0, c];
  else base = [c, 0, x];
  return { r: (base[0] + m) * 255, g: (base[1] + m) * 255, b: (base[2] + m) * 255 };
}

export function ColorPalette({ color, recentColors, eyedropperActive, onColorChange, onEyedropper }: Props) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('wheel');
  const rgb = useMemo(() => hexToRgb(color), [color]);
  const hsv = useMemo(() => rgbToHsv(rgb), [rgb]);

  const updateHsv = (next: Partial<HSV>) => onColorChange(rgbToHex(hsvToRgb({ ...hsv, ...next })));
  const updateRgb = (key: keyof RGB, value: number) => onColorChange(rgbToHex({ ...rgb, [key]: value }));

  const pickHue = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - (rect.left + rect.width / 2);
    const y = event.clientY - (rect.top + rect.height / 2);
    const degrees = (Math.atan2(y, x) * 180) / Math.PI + 90;
    updateHsv({ h: (degrees + 360) % 360 });
  };

  const pickSaturationValue = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const s = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const v = 1 - Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
    updateHsv({ s, v });
  };

  return (
    <div className="color-dock">
      <button className="current-color" style={{ background: color }} onClick={() => setOpen((value) => !value)} aria-label="くわしい色を選ぶ" />
      <div className="quick-colors" aria-label="基本色">
        {QUICK_COLORS.map((quick) => (
          <button
            key={quick}
            className={quick.toLowerCase() === color.toLowerCase() ? 'quick-color active' : 'quick-color'}
            style={{ background: quick }}
            onClick={() => onColorChange(quick)}
            aria-label={`色 ${quick}`}
          />
        ))}
      </div>
      <button className={eyedropperActive ? 'dock-action active' : 'dock-action'} onClick={onEyedropper} aria-label="スポイト">⌾</button>
      <button className="dock-action" onClick={() => setOpen(true)} aria-label="詳細色">＋</button>

      {open && (
        <section className="color-panel" aria-label="詳細色選択">
          <div className="color-panel-head">
            <strong>カラー</strong>
            <button onClick={() => setOpen(false)} aria-label="閉じる">×</button>
          </div>
          <div className="color-tabs" role="tablist">
            <button className={tab === 'wheel' ? 'active' : ''} onClick={() => setTab('wheel')}>ホイール</button>
            <button className={tab === 'swatches' ? 'active' : ''} onClick={() => setTab('swatches')}>色見本</button>
            <button className={tab === 'sliders' ? 'active' : ''} onClick={() => setTab('sliders')}>スライダー</button>
          </div>

          {tab === 'wheel' && (
            <div className="wheel-tab">
              <div className="hue-wheel" onPointerDown={pickHue} onPointerMove={(event) => { if (event.buttons) pickHue(event); }}>
                <span className="hue-cursor" style={{ transform: `rotate(${hsv.h}deg) translateY(-72px)` }} />
              </div>
              <div
                className="sv-field"
                style={{ backgroundColor: `hsl(${hsv.h} 100% 50%)` }}
                onPointerDown={pickSaturationValue}
                onPointerMove={(event) => { if (event.buttons) pickSaturationValue(event); }}
              >
                <span className="sv-cursor" style={{ left: `${hsv.s * 100}%`, top: `${(1 - hsv.v) * 100}%` }} />
              </div>
            </div>
          )}

          {tab === 'swatches' && (
            <div className="swatch-grid">
              {SWATCHES.map((swatch) => <button key={swatch} style={{ background: swatch }} onClick={() => onColorChange(swatch)} aria-label={swatch} />)}
            </div>
          )}

          {tab === 'sliders' && (
            <div className="rgb-sliders">
              {(['r', 'g', 'b'] as Array<keyof RGB>).map((key) => (
                <label key={key}>
                  <span>{key.toUpperCase()}</span>
                  <input type="range" min="0" max="255" value={rgb[key]} onChange={(event) => updateRgb(key, Number(event.target.value))} />
                  <input type="number" min="0" max="255" value={rgb[key]} onChange={(event) => updateRgb(key, Number(event.target.value))} />
                </label>
              ))}
            </div>
          )}

          <label className="hex-row">
            <span className="hex-preview" style={{ background: color }} />
            <span>HEX</span>
            <input
              value={color.toUpperCase()}
              onChange={(event) => {
                const normalized = normalizeHex(event.target.value);
                if (normalized) onColorChange(normalized);
              }}
              spellCheck={false}
            />
          </label>

          <div className="recent-colors">
            <span>最近使った色</span>
            <div>
              {recentColors.length ? recentColors.map((recent) => <button key={recent} style={{ background: recent }} onClick={() => onColorChange(recent)} aria-label={recent} />) : <small>まだありません</small>}
            </div>
          </div>
          <button className={eyedropperActive ? 'eyedropper-button active' : 'eyedropper-button'} onClick={onEyedropper}>⌾ スポイトでキャンバスから取得</button>
        </section>
      )}
    </div>
  );
}
