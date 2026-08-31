interface SegOption {
  value: string;
  label: string;
}

interface SegmentedControlProps {
  name: string;
  options: SegOption[];
  value: string;
  onChange: (value: string) => void;
}

/** Controllo segmentato su radio nativi, come da design system (nessuno script per lo stato visivo). */
export function SegmentedControl({ name, options, value, onChange }: SegmentedControlProps) {
  return (
    <div className="seg">
      {options.map((opt) => (
        <label className="seg-opt" key={opt.value}>
          <input type="radio" name={name} checked={value === opt.value} onChange={() => onChange(opt.value)} />
          {opt.label}
        </label>
      ))}
    </div>
  );
}
