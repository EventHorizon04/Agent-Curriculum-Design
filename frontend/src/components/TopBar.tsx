import { Link, useNavigate } from 'react-router-dom'
import { CREATING_INTAKE } from '../constants/intakeMode'

/** The one bar every page shares: where you are, and the places you can go
 *  from anywhere. Translucent, so the page scrolls under it like apple.com. */
export default function TopBar({
  showPipeline,
  showCreate,
}: {
  showPipeline: boolean
  showCreate: boolean
}) {
  const navigate = useNavigate()
  return (
    <header
      className="sticky top-0 z-40 flex h-12 items-center gap-4 border-b border-hair text-[0.8125rem] sm:gap-7"
      style={{
        background: 'rgb(251 251 253 / 0.8)',
        backdropFilter: 'saturate(180%) blur(20px)',
        WebkitBackdropFilter: 'saturate(180%) blur(20px)',
        padding: '0 max(1rem, calc(50% - 490px))',
      }}
    >
      <Link to="/" className="min-w-0 truncate font-semibold tracking-tight text-graphite">
        Curriculum Design Agent
      </Link>
      <nav className="ml-auto flex shrink-0 items-center gap-4 sm:gap-7">
        <Link to="/#steps" className="hidden text-graphite/80 hover:text-graphite min-[400px]:inline">
          วิธีใช้
        </Link>
        <Link to="/programs" className="text-graphite/80 hover:text-graphite">
          หลักสูตรของฉัน
        </Link>
        {showPipeline && (
          <Link to="/pipeline" className="text-graphite/80 hover:text-graphite">
            Pipeline
          </Link>
        )}
        {showCreate && (
          <button
            type="button"
            className="btn btn-primary btn-sm whitespace-nowrap"
            onClick={() => navigate('/intake', { state: CREATING_INTAKE })}
          >
            เริ่มหลักสูตรใหม่
          </button>
        )}
      </nav>
    </header>
  )
}
