import { Navigate, Route, Routes } from 'react-router-dom'
import { Inbox } from './routes/Inbox'
import { CheckLabel } from './routes/CheckLabel'
import { CheckBatch } from './routes/CheckBatch'
import { RecordDetail } from './routes/RecordDetail'
import { Store } from './routes/Store'

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/inbox" replace />} />
      <Route path="/inbox" element={<Inbox />} />
      <Route path="/check" element={<CheckLabel />} />
      <Route path="/batch" element={<CheckBatch />} />
      <Route path="/records/:id" element={<RecordDetail />} />
      <Route path="/store" element={<Store />} />
    </Routes>
  )
}
