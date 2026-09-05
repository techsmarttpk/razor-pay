import { RadialBarChart, RadialBar, PolarAngleAxis } from 'recharts'

function colorFor(value: number) {
  if (value >= 90) return '#2dd4a7'
  if (value >= 70) return '#f5c343'
  return '#f0475a'
}

export default function HealthGauge({ label, value }: { label: string; value: number }) {
  const color = colorFor(value)
  const data = [{ name: label, value, fill: color }]
  return (
    <div className="card gauge-card">
      <div style={{ position: 'relative', width: 110, height: 110 }}>
        <RadialBarChart width={110} height={110} innerRadius={38} outerRadius={52} data={data} startAngle={90} endAngle={-270}>
          <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
          <RadialBar background={{ fill: '#1a2432' }} dataKey="value" cornerRadius={20} isAnimationActive={false} />
        </RadialBarChart>
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 20, fontWeight: 700, color,
        }}>
          {value.toFixed(0)}
        </div>
      </div>
      <div className="gauge-label">{label}</div>
    </div>
  )
}
