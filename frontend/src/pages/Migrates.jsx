import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'

const tierClass = (t) => ({ 热档: 'tier-hot', 温档: 'tier-warm', 冷档: 'tier-cold' }[t] || '')

export default function Migrates() {
  const [parts, setParts] = useState([])
  const [jobs, setJobs] = useState([])
  const [book, setBook] = useState(null)
  const [audit, setAudit] = useState([])
  const [pid, setPid] = useState('')
  const [to, setTo] = useState('')
  const [msg, setMsg] = useState('')
  const [msgKind, setMsgKind] = useState('ok')

  const reload = () => {
    api.partitions().then(setParts)
    api.migrates().then(setJobs)
    api.migrateAudit().then(setAudit)
  }
  useEffect(() => { reload(); api.ruleBook().then(b => { setBook(b); setTo('') }) }, [])

  const selected = parts.find(p => String(p.id) === String(pid))

  // 目标温层是否允许，完全查规则矩阵（同一谓词的前端投影），不自行编口径。
  const cellFor = (fromTier, toTier) =>
    book?.matrix.find(m => m.from_tier === fromTier && m.to_tier === toTier)

  const targetOptions = useMemo(() => {
    if (!book || !selected) return []
    return ['热档', '温档', '冷档'].map(t => ({ tier: t, cell: cellFor(selected.tier, t) }))
  }, [book, selected])

  useEffect(() => {
    if (targetOptions.length) {
      const first = targetOptions.find(o => o.cell.allowed)
      setTo(first ? first.tier : '')
    }
  }, [pid, book])

  async function start() {
    setMsg('')
    if (!pid) { setMsgKind('err'); setMsg('请先选择分区'); return }
    try {
      const r = await api.startMigrate({ partition_id: Number(pid), to_tier: to })
      setMsgKind('ok')
      setMsg(`迁移单 ${r.job_id} ${r.status}：${r.from_tier}(${r.from_prefix}) → ${r.to_tier}(${r.to_prefix})`)
      reload()
    } catch (e) {
      setMsgKind('err')
      // 结构化拒因：码 + 文案 + 拒单单号，与规则页同一 reason_code。
      setMsg(e.jobId
        ? `拒单 #${e.jobId} [${e.code}] ${e.reason}`
        : `[${e.code || '错误'}] ${e.message}`)
      reload()
    }
  }

  async function finish(id, ok) {
    try {
      const r = await api.finishMigrate(id, ok)
      setMsgKind('ok')
      setMsg(`迁移单 ${r.job_id} → ${r.status}（${r.tier} · ${r.object_prefix}）`)
      reload()
    } catch (e) { setMsgKind('err'); setMsg(`[${e.code || '错误'}] ${e.message}`) }
  }

  return (
    <div className="page">
      <h1>冷热迁移</h1>
      <p className="lede">仅接受相邻一级迁移；热→冷跨两级整笔拒绝。目标下拉的置灰项与拒单共用同一级差谓词。</p>

      <div className="panel form row">
        <label>分区
          <select value={pid} onChange={e => setPid(e.target.value)}>
            <option value="">选择</option>
            {parts.filter(p => p.status === '在册').map(p => (
              <option key={p.id} value={p.id}>
                {p.part_key}（<span className={tierClass(p.tier)}>{p.tier}</span> · {p.object_prefix}）
              </option>
            ))}
          </select>
        </label>
        <label>目标温层
          <select value={to} onChange={e => setTo(e.target.value)} disabled={!selected}>
            {!selected && <option value="">先选分区</option>}
            {targetOptions.map(o => (
              <option key={o.tier} value={o.tier} disabled={!o.cell.allowed}
                title={o.cell.allowed ? '' : o.cell.reason}>
                {o.tier}{o.cell.allowed ? '' : `（禁：${o.cell.reason_code}）`}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={start} disabled={!selected || !to}>发起迁移</button>
      </div>

      {selected && (
        <p className="muted">
          现行 <span className={`tier-badge ${tierClass(selected.tier)}`}>{selected.tier}</span>
          {' '}归属前缀 <code>{selected.object_prefix}</code>
          {to && cellFor(selected.tier, to) && (
            <> → 目标 <span className={`tier-badge ${tierClass(to)}`}>{to}</span>
              ，级差 {cellFor(selected.tier, to).gap}</>
          )}
        </p>
      )}
      {msg && <p className={msgKind === 'err' ? 'err' : 'msg'}>{msg}</p>}

      <h2>迁移单</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>单号</th><th>分区</th><th>从</th><th>到</th><th>迁前前缀 → 落点前缀</th><th>状态</th><th>拒因</th><th>操作</th></tr>
          </thead>
          <tbody>
            {jobs.map(j => (
              <tr key={j.id} className={j.status === '已拒绝' ? 'row-rejected' : j.status === '已失败' ? 'row-failed' : ''}>
                <td>{j.id}</td>
                <td>{j.part_key}</td>
                <td><span className={`tier-badge ${tierClass(j.from_tier)}`}>{j.from_tier}</span></td>
                <td><span className={`tier-badge ${tierClass(j.to_tier)}`}>{j.to_tier}</span></td>
                <td className="prefix-cell"><code>{j.from_prefix || '—'}</code><br /><code>{j.to_prefix || '—'}</code></td>
                <td>{j.status}</td>
                <td>{j.reject_code
                  ? <span className="reason-chip"><code>{j.reject_code}</code> {j.reject_reason}</span>
                  : (j.note || '')}</td>
                <td>{j.status === '执行中' && (
                  <>
                    <button type="button" onClick={() => finish(j.id, true)}>完成</button>
                    <button type="button" className="ghost" onClick={() => finish(j.id, false)}>失败回滚</button>
                  </>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>迁移审计</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>分区</th><th>事件</th><th>从</th><th>到</th><th>拒因码/说明</th></tr></thead>
          <tbody>
            {audit.map(a => (
              <tr key={a.id}>
                <td>{a.created_at}</td><td>{a.part_key}</td><td>{a.event}</td>
                <td>{a.from_tier || '—'}</td><td>{a.to_tier || '—'}</td>
                <td>{a.reason_code ? <code>{a.reason_code}</code> : ''} {a.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
