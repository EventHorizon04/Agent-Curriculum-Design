import { useState } from 'react'
import api from '../api/client'

export default function Intake() {
  const [status, setStatus] = useState<string>('')

  async function checkHealth() {
    try {
      const res = await api.get<{ status: string }>('/health')
      setStatus(`API: ${res.data.status}`)
    } catch {
      setStatus('API not reachable — is uvicorn running?')
    }
  }

  return (
    <div>
      <h1>Stage 1: Program Intake</h1>
      <p>อัปโหลดเอกสารหลักสูตรและกรอกข้อมูลพื้นฐานของโปรแกรม</p>
      <button onClick={checkHealth}>Test API connection</button>
      {status && <p style={{ marginTop: 8, color: status.includes('not') ? 'red' : 'green' }}>{status}</p>}
    </div>
  )
}
