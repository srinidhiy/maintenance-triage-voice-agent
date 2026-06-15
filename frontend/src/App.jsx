import { Routes, Route, NavLink } from 'react-router-dom'
import EmergencyBoard from './pages/EmergencyBoard'
import Schedule from './pages/Schedule'
import Completed from './pages/Completed'

function Nav() {
  const base = 'px-4 py-2 rounded text-sm font-medium'
  const active = `${base} bg-white text-gray-900 shadow`
  const inactive = `${base} text-gray-600 hover:text-gray-900`

  return (
    <header className="bg-gray-100 border-b border-gray-200 px-6 py-3 flex items-center gap-2">
      <span className="font-semibold text-gray-800 mr-4">Harborview Maintenance</span>
      <NavLink to="/" end className={({ isActive }) => isActive ? active : inactive}>
        Emergency Board
      </NavLink>
      <NavLink to="/schedule" className={({ isActive }) => isActive ? active : inactive}>
        Schedule
      </NavLink>
      <NavLink to="/completed" className={({ isActive }) => isActive ? active : inactive}>
        Completed
      </NavLink>
    </header>
  )
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <Nav />
      <main className="flex-1 p-6">
        <Routes>
          <Route path="/" element={<EmergencyBoard />} />
          <Route path="/schedule" element={<Schedule />} />
          <Route path="/completed" element={<Completed />} />
        </Routes>
      </main>
    </div>
  )
}
