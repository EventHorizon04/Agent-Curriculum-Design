import { BrowserRouter, Route, Routes } from 'react-router-dom'
import StageLayout from './components/StageLayout'
import Intake from './pages/Intake'
import StakeholderNeeds from './pages/StakeholderNeeds'
import SkillExtraction from './pages/SkillExtraction'
import PloSynthesis from './pages/PloSynthesis'
import YloDerivation from './pages/YloDerivation'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<StageLayout />}>
          <Route index element={<Intake />} />
          <Route path="stakeholder-needs" element={<StakeholderNeeds />} />
          <Route path="skill-extraction" element={<SkillExtraction />} />
          <Route path="plo-synthesis" element={<PloSynthesis />} />
          <Route path="ylo-derivation" element={<YloDerivation />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
