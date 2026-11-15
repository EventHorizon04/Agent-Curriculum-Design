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
      className="sticky top-0 z-40 flex h-12 items-center border-b border-hair px-4 text-[0.8125rem] sm:px-6 lg:px-10"
      style={{
        background: 'rgb(251 251 253 / 0.8)',
        backdropFilter: 'saturate(180%) blur(20px)',
        WebkitBackdropFilter: 'saturate(180%) blur(20px)',
      }}
    >
      <div className="mx-auto flex w-full max-w-5xl items-center gap-4 sm:gap-7">
      <Link to="/" className="min-w-0 truncate font-semibold tracking-tight text-graphite">
        Curriculum Design Agent
      </Link>
      <nav aria-label="เมนูหลัก" className="ml-auto flex shrink-0 items-center gap-4 sm:gap-7">
        <Link to="/#steps" className="hidden text-graphite/80 hover:text-graphite min-[400px]:inline">
          วิธีใช้
        </Link>
        <Link to="/my-programs" className="text-graphite/80 hover:text-graphite">
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
      </div>
    </header>
  )
}
