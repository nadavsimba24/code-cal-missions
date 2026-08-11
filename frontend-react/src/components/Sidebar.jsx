export default function Sidebar({ boards, activeId, onSelect }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-dot">🚀</span> CityOS <span className="brand-tag">React POC</span>
      </div>
      <div className="sb-section">לוחות</div>
      <nav className="board-list">
        {boards.map((b) => (
          <button
            key={b.id}
            className={'sb-item' + (b.id === activeId ? ' active' : '')}
            onClick={() => onSelect(b.id)}
          >
            <span className="sb-icon">{b.icon || '📋'}</span>
            <span className="sb-name">{b.name}</span>
            {typeof b.task_count === 'number' && <span className="sb-count">{b.task_count}</span>}
          </button>
        ))}
        {!boards.length && <div className="sb-empty">אין לוחות</div>}
      </nav>
    </aside>
  )
}
