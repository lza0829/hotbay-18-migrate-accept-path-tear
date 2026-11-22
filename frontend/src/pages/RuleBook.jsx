import { useEffect, useState } from 'react'
import { api } from '../api'

const tierClass = (t) => ({ 热档: 'tier-hot', 温档: 'tier-warm', 冷档: 'tier-cold' }[t] || '')

export default function RuleBook() {
  const [book, setBook] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => { api.ruleBook().then(setBook).catch(e => setErr(e.message)) }, [])
  if (err) return <p className="err">{err}</p>
  if (!book) return <p className="muted">加载递进规则…</p>

  const tiers = Object.keys(book.tier_order).sort((a, b) => book.tier_order[a] - book.tier_order[b])

  return (
    <div className="page">
      <h1>递进规则</h1>
      <p className="lede">{book.policy}。规则矩阵与迁移页拒因由后端同一级差谓词重放，不另立口径。</p>

      <section className="panel">
        <h2>温层与目录归属前缀</h2>
        <div className="badge-row">
          {tiers.map(t => (
            <span key={t} className={`tier-badge ${tierClass(t)}`}>
              {t} <code>{book.tier_prefixes[t]}/</code>
            </span>
          ))}
        </div>
        <p className="muted">迁移落点决定前缀：温层列与目录前缀同刷，归属可由落点直接重放。</p>
      </section>

      <section className="panel">
        <h2>级差矩阵（仅相邻一级放行，跨两级整笔拒绝）</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>现行温层 \\ 目标温层</th>{tiers.map(t => <th key={t}>{t}</th>)}</tr>
            </thead>
            <tbody>
              {tiers.map(frm => (
                <tr key={frm}>
                  <td><span className={`tier-badge ${tierClass(frm)}`}>{frm}</span></td>
                  {tiers.map(to => {
                    const cell = book.matrix.find(m => m.from_tier === frm && m.to_tier === to)
                    return (
                      <td key={to} className={cell.allowed ? 'cell-allow' : 'cell-deny'}>
                        <strong>{cell.allowed ? '放行' : '拒绝'}</strong>
                        <span className="muted"> · 级差 {cell.gap > 0 ? `+${cell.gap}` : cell.gap}</span>
                        {!cell.allowed && cell.reason_code && (
                          <div className="reason-chip"><code>{cell.reason_code}</code> {cell.reason}</div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
