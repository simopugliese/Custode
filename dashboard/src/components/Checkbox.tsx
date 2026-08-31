import { Check } from 'lucide-react';

interface CheckboxProps {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
}

export function Checkbox({ checked, onChange, disabled }: CheckboxProps) {
  return (
    <button
      type="button"
      className="cbx"
      data-on={checked ? '1' : '0'}
      onClick={onChange}
      disabled={disabled}
      aria-pressed={checked}
    >
      <Check size={12} />
    </button>
  );
}
