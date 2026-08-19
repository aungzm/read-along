import { useState } from "react"

import { AppShell } from "@/app/app-shell"
import { Hero } from "@/app/hero"
import { Skeleton } from "@/components/ui/skeleton"
import { ActiveRunCard } from "@/features/ingest/active-run-card"
import { IngestSection, type IngestFiles } from "@/features/ingest/ingest-section"
import type { ResultNames } from "@/features/ingest/result-file"
import { JobList } from "@/features/jobs/job-list"
import { useJobEvents } from "@/features/jobs/use-job-events"
import { useCreateJob, useJobs } from "@/features/jobs/use-jobs"

export function App() {
  const jobs = useJobs()
  const createJob = useCreateJob()
  const [files, setFiles] = useState<IngestFiles>({ epub: null, audio: null })
  // Source file names per job, so the fake download can name them. Jobs from
  // before this session simply have no entry and get a generic file.
  const [resultNames, setResultNames] = useState<Record<string, ResultNames>>({})
  const allJobs = jobs.data ?? []
  const activeJob =
    allJobs.find((job) => job.status === "queued" || job.status === "running") ??
    null
  // The active job has its own live strip above; keep it out of the history.
  const pastJobs = activeJob
    ? allJobs.filter((job) => job.jobId !== activeJob.jobId)
    : allJobs

  useJobEvents(activeJob?.jobId ?? null)

  const canStart = files.epub !== null && files.audio !== null

  function handleStart() {
    const epub = files.epub
    const audio = files.audio
    if (!epub || !audio || activeJob || createJob.isPending) return
    createJob.mutate(
      { epub, audio },
      {
        onSuccess: (job) =>
          setResultNames((prev) => ({
            ...prev,
            [job.jobId]: { epubName: epub.name, audioName: audio.name },
          })),
      },
    )
  }

  return (
    <AppShell>
      <div className="space-y-12">
        <Hero />

        <IngestSection
          files={files}
          onChange={setFiles}
          canStart={canStart}
          isStarting={createJob.isPending}
          isBlocked={activeJob !== null}
          onStart={handleStart}
        />

        <section className="space-y-5">
          <h2 className="border-b border-border/70 pb-3 font-reading text-lg font-medium">
            Alignment jobs
          </h2>

          {activeJob ? <ActiveRunCard job={activeJob} /> : null}

          {jobs.isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : jobs.isError ? (
            <p className="text-sm text-destructive">
              Could not reach the API. Start it with{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                pnpm api:dev
              </code>
              .
            </p>
          ) : pastJobs.length > 0 ? (
            <JobList jobs={pastJobs} resultNames={resultNames} />
          ) : allJobs.length === 0 ? (
            <JobList jobs={[]} resultNames={resultNames} />
          ) : null}
        </section>
      </div>
    </AppShell>
  )
}

export default App
