// wangEditor's bundled Prism must only highlight its own editor on request.
// Automatic page scans would rewrite the published article's code nodes when
// the AI drawer lazily loads the draft editor, invalidating selection ranges.
const runtime = globalThis as typeof globalThis & { Prism?: { manual?: boolean } }
runtime.Prism ||= {}
runtime.Prism.manual = true
