import { api } from '../api/client'
import type { Job } from '../api/client'

/** Start a job and resolve once it stops running. The API also exposes SSE at
 *  /jobs/{id}/events; polling is enough for a queue this size. */
export async function runJob(body: Record<string, unknown>): Promise<Job> {
  let job = await api<Job>('/jobs', { method: 'POST', body })
  while (job.state === 'running') {
    await new Promise((r) => setTimeout(r, 350))
    job = await api<Job>(`/jobs/${job.id}`)
  }
  return job
}
