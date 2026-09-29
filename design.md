# UI Design: The Lenny Growth Assistant

## Product layout

The application uses a three-panel workspace on desktop:

1. **Conversation sidebar** — starts a new chat and lists persisted sessions ordered by recent activity.
2. **Grounded chat** — shows the user question, assistant answer, citations, loading state, and a composer.
3. **Artifact viewer** — lists generated Markdown/HTML artifacts and previews the selected artifact.

At widths below 1050px the artifact panel collapses. At mobile widths the sidebar becomes a horizontal session strip and the chat becomes the primary full-width surface.

## Interaction principles

- Make grounding visible: every successful transcript answer displays source cards with the episode title and source URL.
- Make uncertainty explicit: retrieval misses and provider failures are shown as readable inline errors rather than fabricated answers.
- Keep generation reversible: artifacts are stored separately from messages and can be selected again from the viewer.
- Keep model state visible: the runtime bar shows database health, Ollama availability, the active provider, and model label.
- Preserve keyboard flow: Enter sends a message and Shift+Enter creates a new line.

## Content and visual system

The visual language is deliberately calm and editorial: dark graphite surfaces, muted blue-gray borders, a lime accent for actions and citations, and Space Grotesk/DM Sans typography. The interface avoids decorative motion except for the small typing indicator while a request is in flight.

## Safety behavior

Markdown is rendered with `react-markdown` and does not pass raw HTML through to the host DOM. HTML artifacts are rendered in a sandboxed iframe with a restrictive Content Security Policy that disables network access, storage access, form submission, and host-page access. Artifact content is treated as untrusted model output.

## Accessibility checklist

- Use semantic `header`, `main`, `aside`, `article`, `label`, and `button` elements.
- Keep visible focus states available through browser defaults or component styles.
- Provide iframe titles and accessible labels for conversation and artifact lists.
- Do not use color alone to communicate provider or database status; pair status dots with text.
- Keep controls disabled while their request is in flight to prevent duplicate writes.
