import { avatarUrl } from '../api'
import TaskCard from './TaskCard.jsx'

export default function BoardView({ board }) {
  const groups = board.groups || []
  const tasks = board.tasks || []
  const byGroup = (gid) => tasks.filter((t) => t.group_id === gid)
  const owners = board.owners || []

  return (
    <div className="board">
      <header className="board-head">
        <span className="board-icon">{board.icon || '📋'}</span>
        <h1>{board.name}</h1>
        {owners.length > 0 && (
          <span className="owner-chip" title={owners.map((o) => o.name).join(', ')}>
            <span className="owner-lbl">בעלים</span>
            <img className="av" src={avatarUrl(owners[0])} alt="" />
            <span>{owners[0].name}</span>
            {owners.length > 1 && <span className="owner-more">+{owners.length - 1}</span>}
          </span>
        )}
        <span className="board-role">{board.my_role}</span>
      </header>

      <div className="kanban">
        {groups.map((g) => {
          const items = byGroup(g.id)
          return (
            <section className="column" key={g.id}>
              <div className="col-head" style={{ borderTopColor: g.color || '#c4c4c4' }}>
                <span className="col-dot" style={{ background: g.color || '#c4c4c4' }} />
                <span className="col-name">{g.name}</span>
                <span className="col-count">{items.length}</span>
              </div>
              <div className="col-body">
                {items.map((t) => (
                  <TaskCard key={t.id} task={t} />
                ))}
                {!items.length && <div className="col-empty">אין פריטים</div>}
              </div>
            </section>
          )
        })}
        {!groups.length && <div className="empty">ללוח אין קבוצות</div>}
      </div>
    </div>
  )
}
