import { NavLink, Outlet } from 'react-router-dom'

const stages = [
  { path: '/', label: 'Stage 1: Intake' },
  { path: '/stakeholder-needs', label: 'Stage 2: Stakeholder Needs' },
  { path: '/skill-extraction', label: 'Stage 3: Skill Extraction' },
  { path: '/plo-synthesis', label: 'Stage 4: PLO Synthesis' },
  { path: '/ylo-derivation', label: 'Stage 5: YLO Derivation' },
]

export default function StageLayout() {
  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: 'sans-serif' }}>
      <nav style={{ width: 240, padding: 16, borderRight: '1px solid #ddd', background: '#f9f9f9' }}>
        <h2 style={{ fontSize: 14, marginBottom: 16 }}>Curriculum Agent</h2>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {stages.map((s) => (
            <li key={s.path} style={{ marginBottom: 8 }}>
              <NavLink
                to={s.path}
                end={s.path === '/'}
                style={({ isActive }) => ({
                  fontWeight: isActive ? 'bold' : 'normal',
                  color: isActive ? '#0066cc' : '#333',
                  textDecoration: 'none',
                  fontSize: 13,
                })}
              >
                {s.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main style={{ flex: 1, padding: 24 }}>
        <Outlet />
      </main>
    </div>
  )
}
