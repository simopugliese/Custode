export function Money({ value, unit = ' €' }: { value: number; unit?: string }) {
  const [whole, decimals] = value.toFixed(2).split('.');
  return (
    <>
      {whole}
      <small>
        ,{decimals}
        {unit}
      </small>
    </>
  );
}

export function Percent({ value }: { value: number }) {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  const [whole, frac] = Math.abs(value).toFixed(1).split('.');
  return (
    <>
      {sign}
      {whole}
      <small>,{frac} %</small>
    </>
  );
}
