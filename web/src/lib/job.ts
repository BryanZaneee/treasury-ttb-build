import { api } from '../api/client'
import type { Job } from '../api/client'

/** A job that stopped in the `error` state. Thrown so callers land in the
 *  mutation's onError rather than reporting a rejected commit as a success. */
export class JobError extends Error {}

// A worker killed mid-job leaves the document at `running` forever, so the
// wait is bounded rather than polling at 350 ms until the tab closes. Ten
// minutes is PRD §8's 300-record ceiling with room over it.
const POLL_MS = 350
const MAX_ATTEMPTS = 1_700

/** Poll a job until it stops running. Throws if it stopped on an error, or if
 *  it never stopped. The API also exposes SSE at /jobs/{id}/events; polling is
 *  enough for a queue this size. */
export async function waitForJob(started: Job, onTick?: (job: Job) => void): Promise<Job> {
  let job = started
  for (let attempt = 0; job.state === 'running'; attempt++) {
    if (attempt >= MAX_ATTEMPTS) {
      throw new JobError('The job stopped reporting progress. Check the inbox for what filed.')
    }
    onTick?.(job)
    await new Promise((r) => setTimeout(r, POLL_MS))
    job = await api<Job>(`/jobs/${job.id}`)
  }
  if (job.state === 'error') throw new JobError(job.error || 'The job failed.')
  return job
}

/** Start a job and resolve once it stops running. */
export async function runJob(body: Record<string, unknown>): Promise<Job> {
  return waitForJob(await api<Job>('/jobs', { method: 'POST', body }))
}
