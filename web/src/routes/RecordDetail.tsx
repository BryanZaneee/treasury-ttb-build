import { useParams } from 'react-router-dom'

export function RecordDetail() {
  const { id } = useParams<{ id: string }>()
  return <h1>Determination view — {id}</h1>
}
