# ScriptFlow AI Sources and Rights

## Runtime libraries

- FastAPI, Uvicorn, Pydantic, pytest, HTTPX: open-source Python packages installed
  from PyPI; review their current package licences before distribution.
- FFmpeg/FFprobe: external FFmpeg build. Use a trusted Windows build and review
  its licensing terms for the selected build before commercial distribution.
- `imageio-ffmpeg`: development fallback that bundles FFmpeg only. It does not
  provide FFprobe and is not sufficient for final output validation.
- `pyttsx3`: optional local Windows TTS adapter. The installed system voice and
  its terms are outside this application and must be reviewed separately.
- React, Vite, React Router, Lucide React, and TypeScript: frontend packages
  installed through the `frontend/package.json` manifest. Review the package
  licences before redistribution.

## Media providers

- Mock provider: creates synthetic, labelled test clips. These are not stock
  footage and must not be represented as licensed media.
- Pixabay provider: uses the official video API endpoint
  `https://pixabay.com/api/videos/` only when `PIXABAY_API_KEY` is configured.
  Search results are cached locally for 24 hours, consistent with the
  documentation's caching requirement, and requests use bounded retries.
  Source records include the API result ID, source page, contributor attribution
  when supplied, and a link to Pixabay's current
  [Content License](https://pixabay.com/service/license/). The application
  records no specific licence grant; verify current Pixabay terms and the
  individual asset details before redistribution or commercial use.
- Pexels provider: retained for compatibility and uses the official Pexels video
  API only when `FOOTAGE_PROVIDER=pexels` and `PEXELS_API_KEY` are configured.
  Source records include the API result ID, source URL, creator attribution
  when supplied, and a link to the current [Pexels license](https://www.pexels.com/license/).
  Verify current terms and attribution requirements before release.

No scraped URLs, watermarked clips, copyrighted films, or unverified media are
used by the implementation.

The deterministic Pixabay metadata matching strategy tokenizes the scene query
and Pixabay tags, scores their overlap, then ranks ties by resolution, duration,
and aspect-ratio suitability. This is a lexical heuristic, not an LLM or
semantic embedding model. The video renderer currently does not add music or
crossfade transitions.
