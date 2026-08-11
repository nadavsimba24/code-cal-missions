import { STATUS, PRIORITY, avatarUrl } from '../api'

function fmtDate(iso) {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleDateString('he-IL', { day: '2-digit', month: 'short' })
  } catch {
    return null
  }
}

export default function TaskCard({ task }) {
  const st = STATUS[task.status] || { he: task.status, c: '#c4c4c4' }
  const pr = PRIORITY[task.priority]
  const assignees = task.assignees || []
  const due = fmtDate(task.due_date)

  return (
    <article className="card">
      <div className="card-title">{task.title}</div>
      <div className="card-meta">
        <span className="pill" style={{ background: st.c }}>{st.he}</span>
        {pr && <span className="pill ghost" style={{ color: pr.c, borderColor: pr.c }}>{pr.he}</span>}
        {due && <span className="due">🗓 {due}</span>}
      </div>
      {assignees.length > 0 && (
        <div className="assignees">
          {assignees.slice(0, 4).map((a) => (
            <img key={a.id} className="av" src={avatarUrl(a)} title={a.name} alt="" />
          ))}
          {assignees.length > 4 && <span className="av more">+{assignees.length - 4}</span>}
        </div>
      )}
    </article>
  )
}
