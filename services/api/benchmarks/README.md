# Real-book integration benchmarks

From `services/api`, with the virtualenv activated:

```sh
pip install -e ".[dev,transcribe]"
python -m benchmarks.real_books --prepare-only
python -m benchmarks.real_books
```

The first command downloads two text/audio pairs and builds story-only EPUB 3
fixtures. The second exercises the real FastAPI upload, job processing and
download endpoints in-process, using real faster-whisper `small.en` CPU inference.
No separately running server is needed. The model downloads on first use.
Allow several minutes or longer depending on the machine.

Use `--pair gift-of-the-magi` or `--pair tell-tale-heart` to run just one.
`--timeout 3600` sets the job deadline in seconds; Python cannot forcibly stop
an already-running transcription thread, so shutdown may wait for it.

## Sources and preparation

| Story | Text | Recording |
| --- | --- | --- |
| The Gift of the Magi | [Gutenberg 7256](https://www.gutenberg.org/ebooks/7256) | [Betsie Bush, LibriVox](https://librivox.org/the-gift-of-the-magi-by-o-henry/) |
| The Tell-Tale Heart | [Gutenberg 2148](https://www.gutenberg.org/ebooks/2148) | [Don Morgan, section 10](https://librivox.org/short-story-collection-001/) |

The downloaded text is the edition linked from each LibriVox catalog entry.
Sources are public domain in the USA; check local status elsewhere.
The original Gutenberg text, including its license, is retained as `original.txt`.
Fixtures omit book headings, Gutenberg boilerplate and other stories, join wrapped
lines within paragraphs, and retain the story wording. Audio is untrimmed, including
spoken introductions and credits. These are generated EPUBs, not Gutenberg's EPUB
downloads: they isolate narration alignment from arbitrary publisher formatting.

Downloads are cached in ignored `benchmarks/data/`. Each pair has `book.epub`,
`audio.mp3`, and `sources.json` containing source URLs, reader and SHA-256 hashes.
These can also be uploaded manually through the web app. Upstream sources may
change; retain the local files and hashes when comparing runs.

## Results and pass criteria

`data/report.json` contains job status, elapsed seconds, sentence coverage,
unmatched sentences, structural timing issues and all generated sentence timings.
Each pair also retains `transcript.json`, its job workspace, and (on success)
`result.epub`. The command exits nonzero if either pair fails, including network,
dependency or transcription errors. It does not relax the app's full-coverage gate.
Partial coverage is a useful benchmark result, **not a passing integration test**.

Successful downloads are checked for SMIL files, referenced XHTML anchors and
audio resources. The existing pipeline checks timing order and validity. EPUBCheck
runs during packaging if installed (`epubcheck` on PATH or `EPUBCHECK_JAR`);
without it this is structural checking, not full EPUB conformance validation.

Coverage does not measure acoustic accuracy. Listen in a Media Overlay-capable
reader and manually annotate reference sentence boundaries before claiming a
millisecond accuracy score. No manually timed reference is included yet.

## Automation

The **Real-book benchmarks** GitHub Actions workflow can be run manually from
Actions. It installs transcription dependencies, runs both pairs and uploads
reports/transcripts even on failure. Audio and generated books stay out of Git.
CI also installs EPUBCheck 5.2.1, validates the source EPUBs, and uses it for
packaged output validation. Java/EPUBCheck are optional for local runs.
The normal `python -m pytest` suite remains fast and offline; real transcription
is deliberately separate from ordinary unit tests.
