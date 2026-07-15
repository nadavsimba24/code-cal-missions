import { useEffect, useState } from 'react'
import { getBoards, getBoard } from './api'
import Sidebar from './components/Sidebar.jsx'
import BoardView from './components/BoardView.jsx'

export default function App() {
  const [boards, setBoards] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [board, setBoard] = useState(null)
  const [error, setError] = useState(null)

  // load the board list once
  useEffect(() => {
    getBoards()
      .then((bs) => {
        setBoards(bs)
        if (bs.length) setActiveId(bs[0].id)
      })
      .catch((e) => setError(String(e.message || e)))
  }, [])

  // load the selected board's detail whenever it changes
  useEffect(() => {
    if (activeId == null) return
    setBoard(null)
    getBoard(activeId)
      .then(setBoard)
      .catch((e) => setError(String(e.message || e)))
  }, [activeId])

  if (error) {
    return (
      <div className="empty">
        <b>שגיאה בטעינה:</b> {error}
        <div className="hint">ודא שהשרת רץ על http://localhost:8000</div>
      </div>
    )
  }

  return (
    <div className="app">
      <Sidebar boards={boards} activeId={activeId} onSelect={setActiveId} />
      <main className="main">
        {board ? <BoardView board={board} /> : <div className="empty">טוען לוח…</div>}
      </main>
    </div>
  )
}
