import { useEffect, useState } from 'react'
import { api } from '../api'

const today = () => new Date().toISOString().slice(0, 10)
const TIER_PREFIX = { 热档: 'hot', 温档: 'warm', 冷档: 'cold' }
const tierClass = (t) => ({ 热档: 'tier-hot', 温档: 'tier-warm', 冷档: 'tier-cold' }[t] || '')

export default function Partitions() {
  const [rows, setRows] = useState([])
  const [vaults, setVaults] = useState([])
  const [msg, setMsg] = useState('')
  const [form, setForm] = useState({
    part_key: '', title: '', release_day: today(), vault_id: 1, tier: '热档', object_prefix: 'hot/新片/',
    clip_key: '', clip_bytes: 5000000, clip_note: '正片段',
  })
  const reload = () => api.partitions().then(setRows)
  useEffect(() => { reload(); api.vaults().then(setVaults) }, [])

  function patch(k, v) {
    setForm(f => {
      const next = { ...f, [k]: v }
      // 温层一变，归属前缀首段跟着切，入口即与温层自洽。
      if (k === 'tier') {
        const rest = f.object_prefix.includes('/') ? f.object_prefix.split('/').slice(1).join('/') : '新片/'
        next.object_prefix = `${TIER_PREFIX[v]}/${rest}`
      }
      return next
    })
  }

  async function submit(e) {
    e.preventDefault()
    setMsg('')
    try {
      await api.createPartition({
        part_key: form.part_key,
        title: form.title,
        release_day: form.release_day,
        vault_id: Number(form.vault_id),
        tier: form.tier,
        object_prefix: form.object_prefix,
        clips: [{ object_key: form.clip_key || `${form.object_prefix}seg-01.bin`, bytes: Number(form.clip_bytes), note: form.clip_note }],
      })
      setMsg('登记成功')
      reload()
    } catch (err) { setMsg(err.message) }
  }
  return (
    <div className="page">
      <h1>分区册</h1>
      <form className="panel form" onSubmit={submit}>
        <h2>分区登记</h2>
        <label>分区键<input value={form.part_key} onChange={e => patch('part_key', e.target.value)} required /></label>
        <label>片名<input value={form.title} onChange={e => patch('title', e.target.value)} required /></label>
        <label>发行日<input type="date" value={form.release_day} onChange={e => patch('release_day', e.target.value)} /></label>
        <label>片库间<select value={form.vault_id} onChange={e => patch('vault_id', e.target.value)}>
          {vaults.map(v => <option key={v.id} value={v.id}>{v.name}</option>)}
        </select></label>
        <label>温层<select value={form.tier} onChange={e => patch('tier', e.target.value)}>
          <option>热档</option><option>温档</option><option>冷档</option>
        </select></label>
        <label>对象前缀（首段须与温层一致）<input value={form.object_prefix} onChange={e => patch('object_prefix', e.target.value)} /></label>
        <label>素材对象键<input value={form.clip_key} onChange={e => patch('clip_key', e.target.value)} placeholder="可空则自动" /></label>
        <label>字节数<input type="number" value={form.clip_bytes} onChange={e => patch('clip_bytes', e.target.value)} /></label>
        <button type="submit">登记分区</button>
        {msg && <p className="msg">{msg}</p>}
      </form>
      <div className="table-wrap">
        <table>
          <thead><tr><th>分区键</th><th>片名</th><th>温层</th><th>归属前缀</th><th>片库间</th><th>段数</th><th>状态</th></tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id}>
                <td>{r.part_key}</td>
                <td>{r.title}</td>
                <td><span className={`tier-badge ${tierClass(r.tier)}`}>{r.tier}</span></td>
                <td><code>{r.object_prefix}</code></td>
                <td>{r.vault_name}</td><td>{r.clip_count}</td><td>{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
