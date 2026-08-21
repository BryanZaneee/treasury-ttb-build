import { api } from '../api/client'
import type { Job } from '../api/client'

/** Thrown so a failed job lands in the mutation's onError, not in onSuccess. */
export class JobError extends Error {}

// A worker killed mid-job leaves the document `running` forever, so the wait is
// bounded: ten minutes is PRD §8's 300-record ceiling with room over it.
const POLL_MS = 350
const MAX_ATTEMPTS = 1_700

/** Poll a job until it stops. Throws if it errored, or if it never stopped. */
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
