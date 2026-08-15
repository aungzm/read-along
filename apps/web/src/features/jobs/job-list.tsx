import { Clock01Icon, Download01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"

import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { STAGE_LABELS, type Job } from "@/lib/api"
import { downloadResultFile, type ResultNames } from "@/features/ingest/result-file"
import { useCancelJob } from "./use-jobs"
import { JobStatusBadge } from "./status-badge"

function isActive(job: Job) {
  return job.status === "queued" || job.status === "running"
}

function JobRow({ job, names }: { job: Job; names?: ResultNames }) {
  const cancelJob = useCancelJob()
  const active = isActive(job)
  const percent = Math.round(job.progress * 100)

  return (
    <li className="py-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <p className="truncate font-reading text-[0.95rem] font-medium">
            {job.title}
          </p>
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            <span>{job.stage ? STAGE_LABELS[job.stage] : job.status}</span>
            {active && job.progress > 0 ? (
              <span className="tabular-nums">{percent}%</span>
            ) : null}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <JobStatusBadge status={job.status} />
          {active ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={cancelJob.isPending}
              onClick={() => cancelJob.mutate(job.jobId)}
            >
              Cancel
            </Button>
          ) : null}
          {job.status === "succeeded" ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => downloadResultFile(job, names)}
            >
              <HugeiconsIcon icon={Download01Icon} />
              Download
            </Button>
          ) : null}
        </div>
      </div>

      {active ? <Progress className="mt-3" value={percent} /> : null}
      {job.error ? (
        <p className="mt-2 text-sm text-destructive">{job.error}</p>
      ) : null}
    </li>
  )
}

export function JobList({
  jobs,
  resultNames,
}: {
  jobs: Job[]
  resultNames: Record<string, ResultNames>
}) {
  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border px-6 py-14 text-center">
        <HugeiconsIcon
          icon={Clock01Icon}
          className="size-5 text-muted-foreground"
        />
        <p className="max-w-[34ch] text-sm text-muted-foreground">
          No alignments yet. Pick an EPUB and its audio above to start one.
        </p>
      </div>
    )
  }

  return (
    <ul className="divide-y divide-border/70">
      {jobs.map((job) => (
        <JobRow key={job.jobId} job={job} names={resultNames[job.jobId]} />
      ))}
    </ul>
  )
}
