import { useEffect, useState } from 'react'
import { api } from '../api'

const tierClass = (t) => ({ 热档: 'tier-hot', 温档: 'tier-warm', 冷档: 'tier-cold' }[t] || '')

export default function Home() {
  const [o, setO] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.overview().then(setO).catch(e => setErr(e.message)) }, [])
  if (err) return <p className="err">{err}</p>
  const _ok = o && o.surface_ok;
  if (!o) return <p className="muted">加载总览…</p>
  const tierCards = ['热档', '温档', '冷档'].map(k => [k, o[k]])
  const otherCards = [
    ['迁移执行中', o.迁移执行中], ['迁移已拒绝', o.迁移已拒绝],
    ['待销毁候选', o.待销毁候选], ['目录对象', o.目录对象],
  ]
  return (
    <div className="page">
      <header className="hero">
        <p className="eyebrow">影院素材温层</p>
        <h1>热档片间</h1>
        <p className="lede">分区在册，逐级沉降（热→温→冷，禁止跨两级直达），片龄到期可销毁，目录与元数据互证。</p>
      </header>

      <div className="badge-row">
        {(o.温层前缀 || []).map(x => (
          <span key={x.tier} className={`tier-badge ${tierClass(x.tier)}`}>
            {x.tier} <code>{x.prefix}</code>
          </span>
        ))}
      </div>

      <div className="stat-grid">
        {tierCards.map(([k, v]) => (
          <div className="stat" key={k}>
            <span className={`tier-badge ${tierClass(k)}`}>{k}</span>
            <strong>{v}</strong>
          </div>
        ))}
        {otherCards.map(([k, v]) => (
          <div className="stat" key={k}><span>{k}</span><strong>{v}</strong></div>
        ))}
      </div>
      <section className="panel">
        <h2>片库间</h2>
        <ul className="plain">
          {o.片库间.map(v => (
            <li key={v.id}>{v.name} · 额定 {v.capacity} · {v.active ? '启用' : '停用'}</li>
          ))}
        </ul>
        {o.最近互证 && (
          <p className="muted">最近互证：{o.最近互证.status} · 漂移 {o.最近互证.drift_count} · {o.最近互证.created_at}</p>
        )}
      </section>
    </div>
  )
}
