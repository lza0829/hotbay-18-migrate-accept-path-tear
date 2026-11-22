export class ApiError extends Error {
  constructor(status, detail) {
    const d = typeof detail === 'object' && detail !== null ? detail : { reason: String(detail) }
    super(d.reason || String(detail))
    this.status = status
    this.code = d.code || ''
    this.reason = d.reason || ''
    this.jobId = d.job_id ?? null
  }
}

async function req(path, opts = {}) {
  const r = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  })
  const text = await r.text()
  let data
  try { data = text ? JSON.parse(text) : null } catch { data = { raw: text } }
  if (!r.ok) {
    const detail = data?.detail ?? data?.raw ?? r.statusText
    throw new ApiError(r.status, detail)
  }
  return data
}

export const api = {
  health: () => req('/健康'),
  overview: () => req('/总览'),
  vaults: () => req('/片库间'),
  partitions: () => req('/分区'),
  clips: (id) => req(`/分区/${id}/素材段`),
  createPartition: (body) => req('/分区', { method: 'POST', body: JSON.stringify(body) }),
  migrates: () => req('/迁移'),
  ruleBook: () => req('/递进规则'),
  migrateAudit: (partitionId) => req(partitionId ? `/迁移审计?partition_id=${partitionId}` : '/迁移审计'),
  startMigrate: (body) => req('/迁移', { method: 'POST', body: JSON.stringify(body) }),
  finishMigrate: (id, success = true) => req(`/迁移/${id}/完成`, { method: 'POST', body: JSON.stringify({ success }) }),
  policies: () => req('/保留策略'),
  destroys: () => req('/销毁流水'),
  runRetention: (body) => req('/保留执行', { method: 'POST', body: JSON.stringify(body) }),
  inventory: () => req('/目录清单'),
  verifyRuns: () => req('/互证流水'),
  runVerify: () => req('/互证', { method: 'POST', body: '{}' }),
  settings: () => req('/设置'),
  setDay: (营业日) => req('/设置/营业日', { method: 'POST', body: JSON.stringify({ 营业日 }) }),
}
