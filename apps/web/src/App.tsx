import { useState } from "react"

import { AppShell } from "@/app/app-shell"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { IngestSection, type IngestFiles } from "@/features/ingest/ingest-section"
import { JobList } from "@/features/jobs/job-list"
import { NewJobForm } from "@/features/jobs/new-job-form"
import { useJobEvents } from "@/features/jobs/use-job-events"
import { useHealth, useJobs } from "@/features/jobs/use-jobs"

function ApiStatus() {
  const health = useHealth()

  if (health.isPending) {
    return <Badge variant="outline">Checking API…</Badge>
  }
  if (health.isError) {
    return <Badge variant="destructive">API offline</Badge>
  }
  return <Badge variant="secondary">API v{health.data.version}</Badge>
}

export function App() {
  const jobs = useJobs()
  const [files, setFiles] = useState<IngestFiles>({ epub: null, audio: null })
  const activeJob =
    jobs.data?.find(
      (job) => job.status === "queued" || job.status === "running",
    ) ?? null

  useJobEvents(activeJob?.jobId ?? null)

  return (
    <AppShell>
      <div className="space-y-8">
        <IngestSection files={files} onChange={setFiles} />

        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="font-heading text-lg font-semibold">Alignment jobs</h1>
            <ApiStatus />
          </div>
          <NewJobForm />
        </section>

        <section>
          {jobs.isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : jobs.isError ? (
            <p className="text-sm text-destructive">
              Could not reach the API. Start it with <code>pnpm api:dev</code>.
            </p>
          ) : (
            <JobList jobs={jobs.data ?? []} />
          )}
        </section>
      </div>
    </AppShell>
  )
}

export default App
