import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useCreateJob } from "./use-jobs"

export function NewJobForm() {
  const [title, setTitle] = useState("")
  const createJob = useCreateJob()
  const trimmed = title.trim()

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!trimmed) return
    createJob.mutate(trimmed, { onSuccess: () => setTitle("") })
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
      <div className="grid min-w-0 flex-1 gap-2">
        <Label htmlFor="job-title">Book title</Label>
        <Input
          id="job-title"
          value={title}
          placeholder="The book to align"
          maxLength={200}
          onChange={(event) => setTitle(event.target.value)}
        />
      </div>
      <Button type="submit" disabled={!trimmed || createJob.isPending}>
        {createJob.isPending ? "Starting…" : "Start job"}
      </Button>
    </form>
  )
}
