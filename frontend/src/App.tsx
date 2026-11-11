import { BrowserRouter, Route, Routes } from 'react-router-dom'
import ApiKeyDialog from './components/ApiKeyDialog'
import StageLayout from './components/StageLayout'
import Programs from './pages/Programs'
import Intake from './pages/Intake'
import StakeholderNeeds from './pages/StakeholderNeeds'
import SkillExtraction from './pages/SkillExtraction'
import NeedAnalysis from './pages/NeedAnalysis'
import PloSynthesis from './pages/PloSynthesis'
import PloReport from './pages/PloReport'
import PloReview from './pages/PloReview'
import Pipeline from './pages/Pipeline'

export default function App() {
  return (
    <BrowserRouter>
      <ApiKeyDialog />
      <Routes>
        <Route element={<StageLayout />}>
          <Route index element={<Programs />} />
          <Route path="intake" element={<Intake />} />
          <Route path="stakeholder-needs" element={<StakeholderNeeds />} />
          <Route path="skill-extraction" element={<SkillExtraction />} />
          <Route path="need-analysis" element={<NeedAnalysis />} />
          <Route path="plo-synthesis" element={<PloSynthesis />} />
          <Route path="plo-report" element={<PloReport />} />
          <Route path="plo-review" element={<PloReview />} />
          <Route path="pipeline" element={<Pipeline />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
